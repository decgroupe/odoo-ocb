# -*- coding: utf-8 -*-
#----------------------------------------------------------
# ir_http modular http routing
#----------------------------------------------------------
import base64
import datetime
import hashlib
import logging
import mimetypes
import os
import re
import sys

import werkzeug
import werkzeug.exceptions
import werkzeug.routing
import werkzeug.urls
import werkzeug.utils

import odoo
from odoo import api, http, models, tools, SUPERUSER_ID
from odoo.exceptions import AccessDenied, AccessError
from odoo.http import request, STATIC_CACHE, content_disposition
from odoo.tools import pycompat, consteq
from odoo.tools.mimetypes import guess_mimetype
from ast import literal_eval
from odoo.modules.module import get_resource_path, get_module_path

_logger = logging.getLogger(__name__)
_logger_routes = logging.getLogger(__name__ + '.routes')

class RequestUID(object):
    def __init__(self, **kw):
        self.__dict__.update(kw)


class ModelConverter(werkzeug.routing.BaseConverter):

    def __init__(self, url_map, model=False):
        super(ModelConverter, self).__init__(url_map)
        self.model = model
        self.regex = r'([0-9]+)'

    def to_python(self, value):
        _uid = RequestUID(value=value, converter=self)
        env = api.Environment(request.cr, _uid, request.context)
        return env[self.model].browse(int(value))

    def to_url(self, value):
        return value.id


class ModelsConverter(werkzeug.routing.BaseConverter):

    def __init__(self, url_map, model=False):
        super(ModelsConverter, self).__init__(url_map)
        self.model = model
        # TODO add support for slug in the form [A-Za-z0-9-] bla-bla-89 -> id 89
        self.regex = r'([0-9,]+)'

    def to_python(self, value):
        _uid = RequestUID(value=value, converter=self)
        env = api.Environment(request.cr, _uid, request.context)
        return env[self.model].browse(int(v) for v in value.split(','))

    def to_url(self, value):
        return ",".join(value.ids)


class SignedIntConverter(werkzeug.routing.NumberConverter):
    regex = r'-?\d+'
    num_convert = int


class IrHttp(models.AbstractModel):
    _name = 'ir.http'
    _description = "HTTP Routing"

    @classmethod
    def _get_converters(cls):
        return {'model': ModelConverter, 'models': ModelsConverter, 'int': SignedIntConverter}

    @classmethod
    def _find_handler(cls, return_rule=False):
        return cls.routing_map().bind_to_environ(request.httprequest.environ).match(return_rule=return_rule)

    @classmethod
    def _auth_method_user(cls):
        request.uid = request.session.uid
        if not request.uid:
            raise http.SessionExpiredException("Session expired")

    @classmethod
    def _auth_method_none(cls):
        request.uid = None

    @classmethod
    def _auth_method_public(cls):
        if not request.session.uid:
            request.uid = request.env.ref('base.public_user').id
        else:
            request.uid = request.session.uid

    @classmethod
    def _authenticate(cls, auth_method='user'):
        try:
            if request.session.uid:
                try:
                    request.session.check_security()
                    # what if error in security.check()
                    #   -> res_users.check()
                    #   -> res_users._check_credentials()
                except (AccessDenied, http.SessionExpiredException):
                    # All other exceptions mean undetermined status (e.g. connection pool full),
                    # let them bubble up
                    request.session.logout(keep_db=True)
            if request.uid is None:
                getattr(cls, "_auth_method_%s" % auth_method)()
        except (AccessDenied, http.SessionExpiredException, werkzeug.exceptions.HTTPException):
            raise
        except Exception:
            _logger.info("Exception during request Authentication.", exc_info=True)
            raise AccessDenied()
        return auth_method

    @classmethod
    def _serve_attachment(cls):
        env = api.Environment(request.cr, SUPERUSER_ID, request.context)
        attach = env['ir.attachment'].get_serve_attachment(request.httprequest.path, extra_fields=['name', 'checksum'])
        if attach:
            wdate = attach[0]['__last_update']
            datas = attach[0]['datas'] or b''
            name = attach[0]['name']
            checksum = attach[0]['checksum'] or hashlib.sha1(datas).hexdigest()

            if (not datas and name != request.httprequest.path and
                    name.startswith(('http://', 'https://', '/'))):
                return werkzeug.utils.redirect(name, 301)

            response = werkzeug.wrappers.Response()
            response.last_modified = wdate

            response.set_etag(checksum)
            response.make_conditional(request.httprequest)

            if response.status_code == 304:
                return response

            response.mimetype = attach[0]['mimetype'] or 'application/octet-stream'
            response.data = base64.b64decode(datas)
            return response

    @classmethod
    def _serve_fallback(cls, exception):
        # serve attachment
        attach = cls._serve_attachment()
        if attach:
            return attach
        return False

    @classmethod
    def _handle_exception(cls, exception):
        # If handle_exception returns something different than None, it will be used as a response

        # This is done first as the attachment path may
        # not match any HTTP controller
        if isinstance(exception, werkzeug.exceptions.HTTPException) and exception.code == 404:
            serve = cls._serve_fallback(exception)
            if serve:
                return serve

        # Don't handle exception but use werkzeug debugger if server in --dev mode
        # Don't intercept JSON request to respect the JSON Spec and return exception as JSON
        # "The Response is expressed as a single JSON Object, with the following members:
        #   jsonrpc, result, error, id"
        if ('werkzeug' in tools.config['dev_mode']
                and not isinstance(exception, werkzeug.exceptions.NotFound)
                and request._request_type != 'json'):
            raise exception

        try:
            return request._handle_exception(exception)
        except AccessDenied:
            return werkzeug.exceptions.Forbidden()

    @classmethod
    def _dispatch(cls):
        # locate the controller method
        try:
            rule, arguments = cls._find_handler(return_rule=True)
            func = rule.endpoint
        except werkzeug.exceptions.NotFound as e:
            return cls._handle_exception(e)

        # check authentication level
        try:
            auth_method = cls._authenticate(func.routing["auth"])
        except Exception as e:
            return cls._handle_exception(e)

        processing = cls._postprocess_args(arguments, rule)
        if processing:
            return processing

        # set and execute handler
        try:
            request.set_handler(func, arguments, auth_method)
            result = request.dispatch()
            if isinstance(result, Exception):
                raise result
        except Exception as e:
            return cls._handle_exception(e)

        return result

    @classmethod
    def _postprocess_args(cls, arguments, rule):
        """ post process arg to set uid on browse records """
        for key, val in list(arguments.items()):
            # Replace uid placeholder by the current request.uid
            if isinstance(val, models.BaseModel) and isinstance(val._uid, RequestUID):
                arguments[key] = val.sudo(request.uid)
                if not val.exists():
                    return cls._handle_exception(werkzeug.exceptions.NotFound())

    @classmethod
    def routing_map(cls):
        if not hasattr(cls, '_routing_map'):
            _logger.info("Generating routing map")
            installed = request.registry._init_modules - {'web'}
            if tools.config['test_enable'] and odoo.modules.module.current_test:
                installed.add(odoo.modules.module.current_test)
            mods = [''] + odoo.conf.server_wide_modules + sorted(installed)
            # Note : when routing map is generated, we put it on the class `cls`
            # to make it available for all instance. Since `env` create an new instance
            # of the model, each instance will regenared its own routing map and thus
            # regenerate its EndPoint. The routing map should be static.
            cls._routing_map = http.routing_map(mods, False, converters=cls._get_converters())
            for rule in cls._routing_map._rules:
                _logger_routes.debug(rule.endpoint.routing)
        return cls._routing_map

    @classmethod
    def _clear_routing_map(cls):
        if hasattr(cls, '_routing_map'):
            del cls._routing_map

    @classmethod
    def content_disposition(cls, filename):
        return content_disposition(filename)

    @classmethod
    def _xmlid_to_obj(cls, env, xmlid):
        return env.ref(xmlid, False)

    @classmethod
    def _check_access_mode(cls, env, id, access_mode, model, access_token=None, related_id=None):
        """
        Implemented by each module to define an additional way to check access.

        :param env: the env of binary_content
        :param id: id of the record from which to fetch the binary
        :param access_mode: typically a string that describes the behaviour of the custom check
        :param model: the model of the object for which binary_content was called
        :param related_id: optional id to check security.
        :return: True if the test passes, else False.
        """
        return False


    @classmethod
    def binary_content(cls, xmlid=None, model='ir.attachment', id=None, field='datas',
                       unique=False, filename=None, filename_field='datas_fname', download=False,
                       mimetype=None, default_mimetype='application/octet-stream',
                       access_token=None, related_id=None, access_mode=None, env=None):
        """ Get file, attachment or downloadable content

        If the ``xmlid`` and ``id`` parameter is omitted, fetches the default value for the
        binary field (via ``default_get``), otherwise fetches the field for
        that precise record.

        :param str xmlid: xmlid of the record
        :param str model: name of the model to fetch the binary from
        :param int id: id of the record from which to fetch the binary
        :param str field: binary field
        :param bool unique: add a max-age for the cache control
        :param str filename: choose a filename
        :param str filename_field: if not create an filename with model-id-field
        :param bool download: apply headers to download the file
        :param str mimetype: mintype of the field (for headers)
        :param related_id: the id of another record used for custom_check
        :param  access_mode: if truthy, will call custom_check to fetch the object that contains the binary.
        :param str default_mimetype: default mintype if no mintype found
        :param str access_token: optional token for unauthenticated access
                                 only available  for ir.attachment
        :param Environment env: by default use request.env
        :returns: (status, headers, content)
        """
        env = env or request.env
        # get object and content
        obj = None
        if xmlid:
            obj = cls._xmlid_to_obj(env, xmlid)
        elif id and model in env.registry:
            obj = env[model].browse(int(id))
        # obj exists
        if not obj or not obj.exists() or field not in obj:
            return (404, [], None)

        # access token grant access
        if model == 'ir.attachment' and access_token:
            obj = obj.sudo()
            if access_mode:
                if not cls._check_access_mode(env, id, access_mode, model, access_token=access_token,
                                             related_id=related_id):
                    return (403, [], None)
            elif not consteq(obj.access_token or u'', access_token):
                return (403, [], None)

        # check read access
        try:
            last_update = obj['__last_update']
        except AccessError:
            return (403, [], None)

        status, headers, content = None, [], None

        # attachment by url check
        module_resource_path = None
        if model == 'ir.attachment' and obj.type == 'url' and obj.url:
            url_match = re.match("^/(\w+)/(.+)$", obj.url)
            if url_match:
                module = url_match.group(1)
                module_path = get_module_path(module)
                module_resource_path = get_resource_path(module, url_match.group(2))
                if module_path and module_resource_path:
                    module_path = os.path.join(os.path.normpath(module_path), '')  # join ensures the path ends with '/'
                    module_resource_path = os.path.normpath(module_resource_path)
                    if module_resource_path.startswith(module_path):
                        with open(module_resource_path, 'rb') as f:
                            content = base64.b64encode(f.read())
                        last_update = pycompat.text_type(os.path.getmtime(module_resource_path))

            if not module_resource_path:
                module_resource_path = obj.url

            if not content:
                status = 301
                content = module_resource_path
        else:
            content = obj[field] or ''

        # filename
        default_filename = False
        if not filename:
            if filename_field in obj:
                filename = obj[filename_field]
            if not filename and module_resource_path:
                filename = os.path.basename(module_resource_path)
            if not filename:
                default_filename = True
                filename = "%s-%s-%s" % (obj._name, obj.id, field)

        # mimetype
        mimetype = 'mimetype' in obj and obj.mimetype or False
        if not mimetype:
            if filename:
                mimetype = mimetypes.guess_type(filename)[0]
            if not mimetype and getattr(env[model]._fields[field], 'attachment', False):
                # for binary fields, fetch the ir_attachement for mimetype check
                attach_mimetype = env['ir.attachment'].search_read(domain=[('res_model', '=', model), ('res_id', '=', id), ('res_field', '=', field)], fields=['mimetype'], limit=1)
                mimetype = attach_mimetype and attach_mimetype[0]['mimetype']
            if not mimetype:
                try:
                    decoded_content = base64.b64decode(content)
                except base64.binascii.Error:  # if we could not decode it, no need to pass it down: it would crash elsewhere...
                    return (404, [], None)
                mimetype = guess_mimetype(decoded_content, default=default_mimetype)

        # extension
        _, existing_extension = os.path.splitext(filename)
        if not existing_extension or default_filename:
            extension = mimetypes.guess_extension(mimetype)
            if extension:
                filename = "%s%s" % (filename, extension)

        headers += [('Content-Type', mimetype), ('X-Content-Type-Options', 'nosniff')]

        # cache
        etag = bool(request) and request.httprequest.headers.get('If-None-Match')
        retag = '"%s"' % hashlib.md5(pycompat.to_text(content).encode('utf-8')).hexdigest()
        status = status or (304 if etag == retag else 200)
        headers.append(('ETag', retag))
        headers.append(('Cache-Control', 'max-age=%s' % (STATIC_CACHE if unique else 0)))

        # content-disposition default name
        if download:
            headers.append(('Content-Disposition', cls.content_disposition(filename)))
        return (status, headers, content)


def convert_exception_to(to_type, with_message=False):
    """ Should only be called from an exception handler. Fetches the current
    exception data from sys.exc_info() and creates a new exception of type
    ``to_type`` with the original traceback.

    If ``with_message`` is ``True``, sets the new exception's message to be
    the stringification of the original exception. If ``False``, does not
    set the new exception's message. Otherwise, uses ``with_message`` as the
    new exception's message.

    :type with_message: str|bool
    """
    etype, original, tb = sys.exc_info()
    try:
        if with_message is False:
            message = None
        elif with_message is True:
            message = str(original)
        else:
            message = str(with_message)

        raise pycompat.reraise(to_type, to_type(message), tb)
    except to_type as e:
        return e

from datetime import date, datetime
from xmlrpc.client import dumps, loads
import xmlrpc.client
import base64

from werkzeug.wrappers import Response

from odoo.http import Controller, dispatch_rpc, request, route
from odoo.service import wsgi_server
from odoo.fields import Date, Datetime
from odoo.tools import lazy


class OdooMarshaller(xmlrpc.client.Marshaller):

    """
    XMLRPC Marshaller that converts date(time) objects to strings in iso8061 format.
    """

    dispatch = dict(xmlrpc.client.Marshaller.dispatch)

    def dump_datetime(self, value, write):
        # override to marshall as a string for backwards compatibility
        value = Datetime.to_string(value)
        self.dump_unicode(value, write)
    dispatch[datetime] = dump_datetime

    def dump_date(self, value, write):
        value = Date.to_string(value)
        self.dump_unicode(value, write)
    dispatch[date] = dump_date

    def dump_lazy(self, value, write):
        v = value._value
        return self.dispatch[type(v)](self, v, write)
    dispatch[lazy] = dump_lazy


# monkey-patch xmlrpc.client's marshaller
xmlrpc.client.Marshaller = OdooMarshaller


class RPC(Controller):
    """Handle RPC connections."""

    def _xmlrpc(self, service):
        """Common method to handle an XML-RPC request."""

        def fix(res):
            """
            This fix is a minor hook to avoid xmlrpclib to raise TypeError exception: 
            - To respect the XML-RPC protocol, all "int" and "float" keys must be cast to string to avoid
              TypeError, "dictionary key must be string"
            - And since "allow_none" is disabled, we replace all None values with a False boolean to avoid
              TypeError, "cannot marshal None unless allow_none is enabled"
            """
            if res is None:
                return False
            elif type(res) == dict:
                return dict((str(key), fix(value)) for key, value in res.items())
            elif type(res) == list:
                return [fix(x) for x in res]
            elif type(res) == tuple:
                return tuple(fix(x) for x in res)
            elif type(res) == bytes:
                return base64.b64encode(res)
            else:
                return res

        data = request.httprequest.get_data()
        params, method = loads(data)
        result = dispatch_rpc(service, method, params)
        result = fix(result)
        return dumps((result,), methodresponse=1, allow_none=False)

    @route("/xmlrpc/<service>", auth="none", methods=["POST"], csrf=False, save_session=False)
    def xmlrpc_1(self, service):
        """XML-RPC service that returns faultCode as strings.

        This entrypoint is historical and non-compliant, but kept for
        backwards-compatibility.
        """
        try:
            response = self._xmlrpc(service)
        except Exception as error:
            response = wsgi_server.xmlrpc_handle_exception_string(error)
        return Response(response=response, mimetype='text/xml')

    @route("/xmlrpc/2/<service>", auth="none", methods=["POST"], csrf=False, save_session=False)
    def xmlrpc_2(self, service):
        """XML-RPC service that returns faultCode as int."""
        try:
            response = self._xmlrpc(service)
        except Exception as error:
            response = wsgi_server.xmlrpc_handle_exception_int(error)
        return Response(response=response, mimetype='text/xml')

    @route('/jsonrpc', type='json', auth="none", save_session=False)
    def jsonrpc(self, service, method, args):
        """ Method used by client APIs to contact OpenERP. """
        return dispatch_rpc(service, method, args)

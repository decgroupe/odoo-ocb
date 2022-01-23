(function (factory) {
    /* global define */
    if (typeof define === 'function' && define.amd) {
        // AMD. Register as an anonymous module.
        define(['jquery'], factory);
    } else {
        // Browser globals: jQuery
        factory(window.jQuery);
    }
}(function ($) {
    // template
    var tmpl = $.summernote.renderer.getTemplate();
    // core functions: range, dom
    var range = $.summernote.core.range;
    var dom = $.summernote.core.dom;

    /**
     * @class plugin.toggleclass 
     * 
     * Toggle Class Plugin  
     */
    $.summernote.addPlugin({
        name: 'toggleClass',
        buttons: { // buttons
            toggleClassDropdown: function () {
                classTags = ["text-muted",
                    "text-primary",
                    "text-warning",
                    "text-danger",
                    "text-success",
                    "alert alert-success figure",
                    "alert alert-info figure",
                    "alert alert-warning figure",
                    "alert alert-danger figure",
                    "btn btn-primary",
                    "btn btn-secondary",];
                var list = '';
                for (var i = 0; i < classTags.length; i++) {
                    list += '<li><a style="display: inline-block;" data-event="toggleClassDropdown" href="#" data-value="' + classTags[i] + '" class="' + classTags[i] + '" >' + classTags[i] + '</a></li>';
                }
                var dropdown = '<ul class="dropdown-menu" style="height: auto; width:400px; max-height: 200px; max-width:600px; overflow-x: hidden;">' + list + '</ul>';

                return tmpl.iconButton('fa fa-css3', {
                    title: 'Toggle CSS class',
                    hide: true,
                    dropdown: dropdown
                });
            },

        },

        events: { // events
            toggleClassDropdown: function (event, editor, layoutInfo, value) {
                document.execCommand('removeFormat');
                var $editable = layoutInfo.editable();
                var rng = range.create();
                if (!rng) {
                    return;
                }
                if (rng.isCollapsed()) {
                    var spans = editor.style.styleNodes(rng);
                    $(spans).toggleClass(value, true);
                    rng.select();
                } else {
                    editor.beforeCommand($editable);
                    $(editor.style.styleNodes(rng)).toggleClass(value, true);
                    editor.afterCommand($editable);
                }
            },
        }
    });
}));

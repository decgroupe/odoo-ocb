#!/usr/bin/env python3
import logging
import os
import sys
import unittest
from unittest.mock import Mock, MagicMock

sys.path.append(os.path.abspath(os.path.join(__file__, "../../../")))

import odoo
import odoo.modules.graph
from odoo.tests.common import BaseCase
from odoo.netsvc import init_logger
import odoo.tests.loader

_logger = logging.getLogger("odoo.tests.test_graph")


class TestGraph(BaseCase):
    """ """

    @classmethod
    def setUpClass(cls):
        cls.addons_path = odoo.tools.config["addons_path"]

    def setUp(self):
        super(TestGraph, self).setUp()
        _logger.info("Execute %s", self._testMethodName)
        odoo.tools.config["addons_path"] = TestGraph.addons_path

    def _add_node(self, graph, name, depends=False, soft_depends=False):
        if isinstance(depends, str):
            depends = [depends]
        if isinstance(soft_depends, str):
            soft_depends = [soft_depends]
        # check if node already exists and update existing data
        node = graph.get(name)
        if node and node.info:
            info = node.info
            if depends:
                info["depends"] = depends
            if soft_depends:
                info["soft_depends"] = soft_depends
        else:
            info = {
                "depends": depends or [],
                "soft_depends": soft_depends or [],
            }
        node_depends = info["depends"] + info["soft_depends"]
        graph.add_node(name, info, node_depends)

    def _log_graph_status(self, graph):
        _logger.info("Graph:\n" + str(graph))
        _logger.info("Final loading order is:\n" + graph._pprint())

    def _generate_base_graph(self):
        graph = odoo.modules.graph.Graph()
        self._add_node(graph, "base")
        self._add_node(graph, "uom", "base")
        self._add_node(graph, "web", "base")
        self._add_node(graph, "auth_totp", "web")
        self._add_node(graph, "barcodes", "web")
        self._add_node(graph, "base_import", "web")
        self._add_node(graph, "base_setup", "web")
        self._add_node(graph, "bus", "web")
        self._add_node(graph, "http_routing", "web")
        self._add_node(graph, "resource", "web")
        self._add_node(graph, "web_editor", "web")
        self._add_node(graph, "web_unsplash", ["base_setup", "web_editor"])
        self._add_node(graph, "web_tour", "web")
        self._add_node(graph, "web_kanban_gauge", "web")
        self._add_node(graph, "mail", ["base", "base_setup", "bus", "web_tour"])
        self._add_node(graph, "auth_signup", ["base_setup", "mail", "web"])
        self._add_node(
            graph,
            "portal",
            ["web", "web_editor", "http_routing", "mail", "auth_signup"],
        )
        self._add_node(graph, "auth_totp_portal", ["portal", "auth_totp"])
        self._add_node(graph, "digest", ["mail", "portal", "resource"])
        self._add_node(
            graph,
            "stock",
            ["product", "barcodes", "digest"],
        )
        self._add_node(graph, "product", ["base", "mail", "uom"])
        return graph

    def test_01_base(self):
        graph = self._generate_base_graph()
        self._log_graph_status(graph)
        lo = list(graph)
        # check that nodes are loaded
        self.assertTrue(graph.get("web") in lo)
        self.assertTrue(graph.get("auth_totp") in lo)
        # check loading order
        self.assertTrue(lo.index(graph.get("auth_totp")) > lo.index(graph.get("web")))

    def test_02_module_post_added(self):
        graph = self._generate_base_graph()
        self._add_node(graph, "auth_ldap", ["base", "base_setup"])
        self._log_graph_status(graph)
        lo = list(graph)
        # check loading order
        self.assertTrue(lo.index(graph.get("auth_ldap")) > lo.index(graph.get("base")))
        self.assertTrue(
            lo.index(graph.get("auth_ldap")) > lo.index(graph.get("base_setup"))
        )
        self.assertTrue(
            lo.index(graph.get("auth_ldap")) > lo.index(graph.get("auth_totp"))
        )

    def test_03_missing_soft_dependency(self):
        graph = self._generate_base_graph()
        self._add_node(graph, "auth_totp", soft_depends="auth_ldap")
        self._log_graph_status(graph)
        lo = list(graph)
        # check that the lazy node exists
        self.assertIsNotNone(graph.get("auth_ldap"))
        # but not returned when the graph is iterated
        self.assertFalse(graph.get("auth_ldap") in lo)

    def test_04_loading_order_with_soft_dependency(self):
        graph = self._generate_base_graph()
        self._add_node(graph, "auth_ldap", ["base", "base_setup"])
        self._add_node(graph, "auth_totp", soft_depends="auth_ldap")
        self._log_graph_status(graph)
        lo = list(graph)
        # check loading order
        self.assertTrue(
            lo.index(graph.get("auth_totp")) > lo.index(graph.get("auth_ldap"))
        )

    def test_05_load_modules_with_missing_soft_dependency(self):
        odoo.tools.config["addons_path"] += ",./tests/addons_core/"
        odoo.modules.initialize_sys_path()
        graph = odoo.modules.graph.Graph()
        cr = Mock(
            execute=MagicMock(return_value=True),
            dictfetchall=MagicMock(return_value=[]),
        )
        graph.add_modules(cr, ["base"])
        graph.add_modules(
            cr,
            [
                # Modules from addons_core
                "foxtrot",
                "charlie",
                "delta",
                "echo",
                "bravo",
                "alpha",
            ],
        )
        self._log_graph_status(graph)
        self.assertTrue(graph.get("base") in graph.get("alpha").parents)

    def test_06_load_modules_with_soft_dependency(self):
        odoo.tools.config["addons_path"] += ",./tests/addons_core/"
        odoo.tools.config["addons_path"] += ",./tests/addons_extra/"
        odoo.modules.initialize_sys_path()
        graph = odoo.modules.graph.Graph()
        cr = Mock(
            execute=MagicMock(return_value=True),
            dictfetchall=MagicMock(return_value=[]),
        )
        graph.add_modules(cr, ["base"])
        graph.add_modules(
            cr,
            [
                # Modules from addons_core
                "foxtrot",
                "charlie",
                "delta",
                "echo",
                "bravo",
                "alpha",
                # Modules from addons_extra
                "golf",
                "hotel",
            ],
        )
        self._log_graph_status(graph)
        self.assertFalse(graph.get("base") in graph.get("alpha").parents)
        self.assertTrue(graph.get("golf") in graph.get("alpha").parents)


if __name__ == "__main__":
    init_logger()
    unittest.main()

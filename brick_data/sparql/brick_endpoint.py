from shutil import copyfile
import pdb
from copy import deepcopy
import os
import arrow
from io import StringIO
import re

import rdflib
from rdflib import RDFS, RDF, OWL, Namespace
from rdflib.namespace import FOAF
from SPARQLWrapper import SPARQLWrapper
from SPARQLWrapper import JSON, SELECT, INSERT, DIGEST, GET, POST, DELETE
LOAD = 'LOAD'
from rdflib import URIRef, Literal

import validators

from .common import VIRTUOSO

def striding_windows(l, w_size):
    curr_idx = 0
    while curr_idx < len(l):
        yield l[curr_idx:curr_idx + w_size]
        curr_idx += w_size

class BrickSparql(object):

    def __init__(self, sparql_url, brick_version, graph, base_ns, load_schema=False):
        self.BRICK_VERSION = brick_version
        self.sparql_url = sparql_url
        self.sparql = SPARQLWrapper(endpoint=self.sparql_url,
                                    updateEndpoint=self.sparql_url + '-auth')
        self.sparql.queryType= SELECT
        self.sparql.setCredentials('dba', 'dba')
        self.sparql.setHTTPAuth(DIGEST)
        self.BASE = Namespace(base_ns)
        self.base_graph = graph
        self.sparql.addDefaultGraph(self.base_graph)
        self.BRICK = Namespace(
            'https://brickschema.org/schema/{0}/Brick#'\
            .format(self.BRICK_VERSION))
        self.BRICK_USE = Namespace(
            'https://brickschema.org/schema/{0}/BrickUse#'\
            .format(self.BRICK_VERSION))
        self.BF = Namespace(
            'https://brickschema.org/schema/{0}/BrickFrame#'\
            .format(self.BRICK_VERSION))
        self.BRICK_TAG = Namespace(
            'https://brickschema.org/schema/{0}/BrickTag#'\
            .format(self.BRICK_VERSION))

        PROV = Namespace('http://www.w3.org/ns/prov#')

        self.namespaces = {
            '': self.BASE,
            'base': self.BASE,
            'brick':self.BRICK,
            'bf': self.BF,
            'brick_tag': self.BRICK_TAG,
            'brick_use': self.BRICK_USE,
            'rdfs': RDFS,
            'rdf': RDF,
            'owl': OWL,
            'foaf': FOAF,
            'prov': PROV,
        }

        self.init_q_prefix()

        if load_schema:
            self._load_schema()
        self.backend = VIRTUOSO

        if self.backend == VIRTUOSO:
            self.data_dir = '/datadrive/synergy/tools/virtuoso/share/virtuoso/vad'

    def init_q_prefix(self):
        self.q_prefix = ''
        for prefix, ns in self.namespaces.items():
            if 'uri' in dir(ns):
                ns_n3 = ns.uri.n3()
            else:
                ns_n3 = ns[''].n3()

            self.q_prefix += 'prefix {0}: {1}\n'.format(prefix, ns_n3)
        self.q_prefix += '\n'

    def _get_sparql(self):
        # If need to optimize accessing sparql object.
        return self.sparql

    def _format_select_res(self, raw_res):
        var_names = raw_res['head']['vars']
        tuples = [[row[var_name]['value'] for var_name in var_names]
              for row in raw_res['results']['bindings']]
        #TODO: Below line is a hack.
        var_names = ['?'+var_name for var_name in var_names]
        return {
            'var_names': var_names,
            'tuples': tuples
        }

    def parse_result(self, res):
        raw_res = res
        common_res = res
        return common_res, raw_res

    def add_graphs_to_select_qstr(self, qstr, graphs=[]):
        if not graphs:
            return qstr
        [prefix, body] = re.split(re.compile('where', re.IGNORECASE), qstr)
        graph_body = '\n'
        for graph in graphs:
            graph_body += 'FROM <{0}>\n'.format(graph)
        return prefix + graph_body + 'where ' + body

    def add_graphs_to_insert_qstr(self, qstr, graphs=[]):
        if graphs:
            graph = graphs[0]
        else:
            graph = self.base_graph
        qstr = 'WITH <{0}>\n'.format(graph) + qstr
        return qstr

    def add_graphs_to_insert_qstr_dep(self, qstr, graphs=[]):
        assert len(graphs) <= 1, 'Cannot insert into multiple graphs. Choose a graph or no graph'
        #if not graphs:
        #    return qstr
        if graphs:
            graph = graphs[0]
        else:
            graph = self.base_graph
        [graph_prefix, body] = re.split(re.compile('insert{', re.IGNORECASE), qstr)
        graph_prefix += 'INSERT{\n'
        graph_prefix += 'GRAPH <{0}> {{'.format(graph)
        splitted_body = re.split('}', body)
        insert_body = splitted_body[0]
        augmented_qstr = graph_prefix + insert_body + '  }\n}' + '}'.join(splitted_body[1:])
        return augmented_qstr

    def update(self, qstr, graphs=[]):
        sparql = self._get_sparql()
        sparql.setMethod(POST)
        sparql.setReturnFormat(JSON)
        query_type = qstr[:6]
        if query_type.upper() == 'INSERT':
            qstr = self.add_graphs_to_insert_qstr(qstr, graphs)
        elif graphs:
            raise Exception('not implemented yet')
        qstr = self.q_prefix + qstr
        sparql.setQuery(qstr)
        raw_res = sparql.query().convert()
        if sparql.queryType == SELECT:
            res = self._format_select_res(raw_res)
        elif sparql.queryType in [INSERT, LOAD, DELETE]:
            res = raw_res # TODO: Error handling here
        return res

    def query(self, qstr, graphs=[], is_update=False):
        sparql = self._get_sparql()
        sparql.setMethod(POST)
        sparql.setReturnFormat(JSON)
        qstr = self.q_prefix + qstr
        if not is_update:
            qstr = self.add_graphs_to_select_qstr(qstr, graphs)
        sparql.setQuery(qstr)
        raw_res = sparql.query().convert()
        if sparql.queryType == SELECT:
            res = self._format_select_res(raw_res)
        elif sparql.queryType in [INSERT, LOAD, DELETE]:
            res = raw_res # TODO: Error handling here
        return res

    def _create_insert_query(self, triples, graph=None):
        if not graph:
            graph = self.base_graph
        q = """
            INSERT DATA {{
                GRAPH <{0}> {{
            """.format(graph)
        for triple in triples:
            triple_str = ' '.join([term.n3() for term in triple]) + ' .\n'
            q += triple_str
        q += """}
            }
            """
        return q

    def _create_delete_query(self, triples, graph=None):
        if not graph:
            graph = self.base_graph
        q = """
            DELETE DATA {{
                GRAPH <{0}> {{
            """.format(graph)
        for triple in triples:
            triple_str = ' '.join([term.n3() for term in triple]) + ' .\n'
            q += triple_str
        q += """}
            }
            """
        return q

    def _is_bool(self, s):
        s = s.lower()
        if s == 'true' or s == 'false':
            return True
        else:
            return False

    def _str2bool(self, s):
        s = s.lower()
        if s == 'true':
            return True
        elif s == 'false':
            return False
        else:
            raise Exception('{0} is not convertible to boolean'.format(s))

    def _is_float(self, s):
        try:
            float(s)
            return True
        except ValueError:
            return False

    def _parse_term(self, term):
        if isinstance(term, rdflib.term.Identifier):
            return term
        elif isinstance(term, str):
            if 'http' == term[0:4]:
                node = URIRef(term)
            elif ':' in term: #TODO: This condition is dangerous.
                [ns, id_] = term.split(':')
                ns = self.namespaces[ns]
                node = ns[id_]
            else:
                if term.isdigit():
                    term = int(term)
                elif self._is_float(term):
                    term = float(term)
                if self._is_bool(term):
                    term = _str2bool(term)
                node = Literal(term)
        else:
            node = Literal(term)
        return node

    def add_ns_prefix(self, ns, prefix):
        ns = Namespace(ns)
        self.namespaces[prefix] = ns
        self.init_q_prefix()

    def make_triple(self, pseudo_s, pseudo_p, pseudo_o, graph=None):
        if not graph:
            graph = self.base_graph
        s = self._parse_term(pseudo_s)
        p = self._parse_term(pseudo_p)
        o = self._parse_term(pseudo_o)
        return (s, p, o)

    def add_triple(self, pseudo_s, pseudo_p, pseudo_o, graph=None):
        self.add_triples([(pseudo_s, pseudo_p, pseudo_o)], graph)

    def add_triples(self, pseudo_triples, graph=None):
        if not graph:
            graph = self.base_graph
        triples = [self.make_triple(*pseudo_triple) for pseudo_triple in pseudo_triples]
        q = self._create_insert_query(triples, graph)
        res = self.query(q, is_update=True)

    def delete_triple(self, pseudo_s, pseudo_p, pseudo_o, graph=None):
        self.delete_triples([(pseudo_s, pseudo_p, pseudo_o)], graph)

    def delete_triples(self, pseudo_triples, graph=None):
        if not graph:
            graph = self.base_graph
        triples = [self.make_triple(*pseudo_triple) for pseudo_triple in pseudo_triples]
        q = self._create_delete_query(triples, graph)
        res = self.query(q, is_update=True)

    def _load_schema(self):
        schema_urls = [str(ns)[:-1] + '.ttl' for ns in
                       [self.BRICK, self.BRICK_USE, self.BF, self.BRICK_TAG]]
        load_query_template = 'LOAD <{0}> into <{1}>'
        for schema_url in schema_urls:
            qstr = load_query_template.format(
                schema_url.replace('https', 'http'), self.base_graph)
            res = self.query(qstr)

    def load_rdffile(self, f, graph=None):
        if not graph:
            graph = self.base_graph
        if (isinstance(f, str) and os.path.isfile(f)) or isinstance(f, StringIO):
            # TODO: Optimize this with using Virtuoso API directly
            new_g = rdflib.Graph()
            new_g.parse(f, format='turtle')
            res = [row for row in new_g.query('select ?s ?p ?o where {?s ?p ?o.}')]
            for rows in striding_windows(res, 500):
                self.add_triples(rows)
        elif isinstance(f, str) and validators.url(f):
            raise Exception('Load ttl not implemented for {0}'.format('url'))
        else:
            raise Exception('Load ttl not implemented for {0}'.format(type(f)))

    def add_brick_instance(self, entity_id, tagset, ns_prefix=None, graph=None):
        if not isinstance(entity_id, URIRef):
            if ns_prefix:
                ns = self.namespaces[ns_prefix]
                entity = ns[entity_id]
            else:
                entity = URIRef(entity_id)
        else:
            entity = entity_id
        tagset = self.BRICK[tagset]
        triples = [(entity, RDF.type, tagset)]
        self.add_triples(triples, graph)
        return entity


if __name__ == '__main__':
    endpoint = BrickEndpoint('http://localhost:8890/sparql', '1.0.3')
    endpoint._load_schema()
    test_qstr = """
        select ?s where {
        ?s rdfs:subClassOf+ brick:Temperature_Sensor .
        }
        """
    res = endpoint.query(test_qstr)
    print(res)

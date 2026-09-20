import unittest
from unittest.mock import patch
from graph import annotate, build_graph
from api_client import normalize_doi
from crossref import get_retraction_evidence
import requests

def node(id, status='no_notice_found'):
    return {'id': id, 'retraction': {'status': status}}
def edge(a,b):
    return {'source':a,'target':b}
class GraphTests(unittest.TestCase):
    def test_shared_papers_keep_shortest_distance_and_citation_direction(self):
        nodes=[node('s','retracted'),node('a'),node('b'),node('c')]
        annotate(nodes,[edge('a','s'),edge('b','s'),edge('b','a'),edge('c','a')],'s')
        self.assertEqual(nodes[2]['distance'],1)
        self.assertEqual(nodes[3]['evidence_path'],['c','a','s'])
        self.assertEqual(nodes[3]['exposure'],'indirect')
    def test_cycles_terminate_and_unknown_is_not_retracted(self):
        nodes=[node('s','unknown'),node('a')]
        annotate(nodes,[edge('a','s'),edge('s','a')],'s')
        self.assertEqual([n['exposure'] for n in nodes],['none','none'])
    def test_multiple_retractions_use_nearest_source(self):
        nodes=[node('s','retracted'),node('a'),node('b','retracted'),node('c')]
        annotate(nodes,[edge('a','s'),edge('b','a'),edge('c','b')],'s')
        self.assertEqual(nodes[3]['evidence_path'],['c','b'])
        self.assertEqual(nodes[2]['exposure'],'retracted')
    def test_doi_normalization(self):
        self.assertEqual(normalize_doi(' HTTPS://doi.org/10.1234/ABC '),'10.1234/abc')
        with self.assertRaises(ValueError):normalize_doi('https://example.com')
    @patch('crossref.fetch')
    def test_retraction_requires_matching_doi_and_type(self,fetch):
        fetch.return_value={'message':{'items':[{'DOI':'10.1234/notice','title':['Notice'],'update-to':[{'DOI':'10.1234/other','type':'retraction'},{'DOI':'10.1234/paper','type':'correction'}]}]}}
        self.assertEqual(get_retraction_evidence('10.1234/paper')['status'],'updated')
        fetch.return_value['message']['items'][0]['update-to'].append({'DOI':'10.1234/PAPER','type':'retraction'})
        self.assertEqual(get_retraction_evidence('10.1234/paper')['status'],'retracted')
    @patch('crossref.fetch',side_effect=requests.Timeout)
    def test_failure_is_unknown(self,fetch):
        self.assertEqual(get_retraction_evidence('10.1234/paper')['status'],'unknown')
    @patch('crossref.fetch',return_value={'message':{'items':[]}})
    def test_absence_is_not_a_clean_bill_of_health(self,fetch):
        self.assertEqual(get_retraction_evidence('10.1234/paper')['status'],'no_notice_found')
    @patch('graph.get_retraction_evidence',return_value={'status':'unknown','notices':[]})
    @patch('graph.get_citing_papers',side_effect=requests.Timeout)
    @patch('graph.get_paper',return_value={'id':'seed','display_name':'Seed'})
    def test_partial_graph_is_labeled(self,*_):
        result=build_graph('10.1234/paper')
        self.assertTrue(result['warnings'])
        self.assertEqual(len(result['nodes']),1)
if __name__=='__main__':unittest.main()

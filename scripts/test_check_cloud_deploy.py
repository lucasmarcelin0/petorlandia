import unittest
from unittest.mock import patch

from check_cloud_deploy import matches, check, heroku, rollback, SiteDown


class DeploymentTests(unittest.TestCase):
    def test_consulta_o_release_mais_novo_sem_ficar_na_primeira_pagina(self):
        from unittest.mock import MagicMock
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'[]'
        with patch('urllib.request.urlopen', return_value=response) as opening:
            heroku('/apps/app/releases', 'secret')
            request = opening.call_args.args[0]
            self.assertEqual(request.get_header('Range'), 'version ..; order=desc, max=1')

    def test_release_antigo_pendente_ou_falho_nao_confirma_publicacao(self):
        self.assertTrue(matches({'status': 'succeeded'}, {'commit': 'a'}, 'a'))
        self.assertFalse(matches({'status': 'succeeded'}, {'commit': 'a'}, 'b'))
        self.assertFalse(matches({'status': 'pending'}, {'commit': 'a'}, 'a'))
        self.assertFalse(matches({'status': 'failed'}, {'commit': 'a'}, 'a'))
        self.assertFalse(matches({'status': 'succeeded'}, {}, ''))

    def test_site_indisponivel_nao_vira_sucesso(self):
        with patch('check_cloud_deploy.heroku', side_effect=[
            [{'version': 2, 'status': 'succeeded', 'slug': {'id': 's'}}],
            {'commit': 'a'}, {'web_url': 'https://example.com/'},
        ]), patch('urllib.request.urlopen', side_effect=TimeoutError):
            with self.assertRaises(SiteDown):
                check('token', 'app', 'a', timeout=0)

    def _releases(self, items):
        from unittest.mock import MagicMock
        import json
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(items).encode()
        return response

    def test_rollback_volta_ao_ultimo_release_bom(self):
        items = [{'id': 'r3', 'version': 3, 'status': 'succeeded'},
                 {'id': 'r2', 'version': 2, 'status': 'failed'},
                 {'id': 'r1', 'version': 1, 'status': 'succeeded'}]
        with patch('urllib.request.urlopen', return_value=self._releases(items)), patch('check_cloud_deploy.heroku_send') as sending:
            self.assertEqual(rollback('t', 'app', {'version': 3})['id'], 'r1')
            sending.assert_called_once_with('/apps/app/releases', 't', 'POST', {'release': 'r1'})

    def test_rollback_nao_passa_por_cima_de_release_mais_novo(self):
        items = [{'id': 'r4', 'version': 4, 'status': 'succeeded'},
                 {'id': 'r3', 'version': 3, 'status': 'succeeded'}]
        with patch('urllib.request.urlopen', return_value=self._releases(items)), patch('check_cloud_deploy.heroku_send') as sending:
            self.assertIsNone(rollback('t', 'app', {'version': 3}))
            sending.assert_not_called()


if __name__ == '__main__':
    unittest.main()

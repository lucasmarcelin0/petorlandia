import unittest
from unittest.mock import patch

from check_cloud_deploy import matches, check, heroku


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
            with self.assertRaises(TimeoutError):
                check('token', 'app', 'a', timeout=0)


if __name__ == '__main__':
    unittest.main()

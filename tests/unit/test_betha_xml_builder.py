from providers.nfse.betha.xml_builder import build_lote_xml, build_rps_xml


def test_build_rps_xml_snapshot():
    payload = {
        "prestador": {
            "cnpj": "12345678000199",
            "im": "12345",
            "endereco": {
                "logradouro": "Rua A",
                "numero": "100",
                "bairro": "Centro",
                "codigo_municipio": "3534301",
                "uf": "SP",
                "cep": "14620000",
            },
        },
        "tomador": {
            "cpf_cnpj": "12345678901",
            "nome": "João da Silva",
            "endereco": {
                "logradouro": "Rua B",
                "numero": "200",
                "bairro": "Centro",
                "codigo_municipio": "3534301",
                "uf": "SP",
                "cep": "14620000",
            },
        },
        "servico": {
            "item_lista": "0701",
            "descricao": "Consulta veterinária",
            "valor": "150.00",
            "aliquota_iss": "2.00",
        },
        "rps": {
            "numero": "45",
            "serie": "A1",
            "data_emissao": "2025-01-01T10:00:00",
        },
    }

    xml = build_rps_xml(payload)

    expected = (
        "<Rps><InfRps Id=\"RPS45\"><IdentificacaoRps><Numero>45</Numero>"
        "<Serie>A1</Serie><Tipo>1</Tipo></IdentificacaoRps>"
        "<DataEmissao>2025-01-01T10:00:00</DataEmissao><Status>1</Status>"
        "<Servico><Valores><ValorServicos>150.00</ValorServicos><Aliquota>2.00</Aliquota>"
        "</Valores><ItemListaServico>0701</ItemListaServico>"
        "<Discriminacao>Consulta veterinária</Discriminacao></Servico>"
        "<Prestador><Cnpj>12345678000199</Cnpj><InscricaoMunicipal>12345</InscricaoMunicipal>"
        "<Endereco><Endereco>Rua A</Endereco><Numero>100</Numero><Complemento/>"
        "<Bairro>Centro</Bairro><CodigoMunicipio>3534301</CodigoMunicipio><Uf>SP</Uf>"
        "<Cep>14620000</Cep></Endereco></Prestador><Tomador>"
        "<IdentificacaoTomador><CpfCnpj><Cpf>12345678901</Cpf></CpfCnpj>"
        "</IdentificacaoTomador><RazaoSocial>João da Silva</RazaoSocial><Endereco>"
        "<Endereco>Rua B</Endereco><Numero>200</Numero><Complemento/>"
        "<Bairro>Centro</Bairro><CodigoMunicipio>3534301</CodigoMunicipio><Uf>SP</Uf>"
        "<Cep>14620000</Cep></Endereco></Tomador></InfRps></Rps>"
    )

    assert xml == expected


def test_build_lote_xml_snapshot():
    payload = {
        "prestador": {"cnpj": "12345678000199", "im": "12345"},
        "tomador": {"cpf_cnpj": "12345678901", "nome": "João"},
        "servico": {"item_lista": "0701", "descricao": "Consulta", "valor": "150.00"},
        "rps": {"numero": "45", "serie": "A1", "data_emissao": "2025-01-01T10:00:00"},
    }

    xml = build_lote_xml([payload])

    expected = (
        "<EnviarLoteRpsEnvio><LoteRps Id=\"Lote1\"><NumeroLote>1</NumeroLote>"
        "<Cnpj>12345678000199</Cnpj><InscricaoMunicipal>12345</InscricaoMunicipal>"
        "<QuantidadeRps>1</QuantidadeRps><ListaRps>"
        "<Rps><InfRps Id=\"RPS45\"><IdentificacaoRps><Numero>45</Numero>"
        "<Serie>A1</Serie><Tipo>1</Tipo></IdentificacaoRps><DataEmissao>2025-01-01T10:00:00"
        "</DataEmissao><Status>1</Status><Servico><Valores><ValorServicos>150.00</ValorServicos>"
        "</Valores><ItemListaServico>0701</ItemListaServico><Discriminacao>Consulta</Discriminacao></Servico>"
        "<Prestador><Cnpj>12345678000199</Cnpj><InscricaoMunicipal>12345</InscricaoMunicipal>"
        "</Prestador><Tomador><IdentificacaoTomador><CpfCnpj><Cpf>12345678901</Cpf></CpfCnpj>"
        "</IdentificacaoTomador><RazaoSocial>João</RazaoSocial></Tomador></InfRps></Rps>"
        "</ListaRps></LoteRps></EnviarLoteRpsEnvio>"
    )

    assert xml == expected

# NFS-e por município: Belo Horizonte (MG) e Orlândia (SP)

> **Nota importante**
> Não foi possível consultar as documentações oficiais dos provedores neste ambiente por bloqueio de acesso externo (proxy 403). Este documento registra o que precisa ser identificado em cada município, a estrutura de coleta e **campos que devem ser confirmados** nas fontes oficiais assim que o acesso estiver disponível.

## 1) Identificação do provedor, endpoints e autenticação

### Belo Horizonte (MG)
- **Provedor municipal**: **a confirmar** (portal NFS-e da Prefeitura de Belo Horizonte).
- **URL de produção / homologação**: **a confirmar**.
- **WSDL/Endpoints**: **a confirmar** (normalmente serviços SOAP).
- **Autenticação**: **a confirmar** (tipicamente certificado digital A1/A3, assinatura XML e credenciais do emitente).
- **Certificados**: **a confirmar** (cadeia ICP-Brasil e regras de TLS/SSL do provedor).
- **Layout XML/RPS**: **a confirmar** (normalmente baseado em ABRASF; versão precisa precisa ser validada).

### Orlândia (SP)
- **Provedor municipal**: **a confirmar** (portal NFS-e da Prefeitura de Orlândia).
- **URL de produção / homologação**: **a confirmar**.
- **WSDL/Endpoints**: **a confirmar**.
- **Autenticação**: **a confirmar**.
- **Certificados**: **a confirmar**.
- **Layout XML/RPS**: **a confirmar**.

## 2) Diferenças de fluxo

> **Observação:** os fluxos abaixo são o padrão conceitual de integração NFS-e.
> A confirmação se a emissão é **síncrona** ou **assíncrona** depende do provedor
> e deve ser validada nas respectivas notas técnicas.

### Fluxos a verificar em cada município
- **Emissão (síncrona vs. assíncrona)**:
  - Síncrona: envio de RPS e retorno imediato da NFS-e.
  - Assíncrona: envio de lote, retorno de protocolo, consulta posterior do lote.
- **Consulta de lote**: operação para verificar processamento do lote e obter NFS-e.
- **Cancelamento**: operação para cancelar NFS-e emitida (com possíveis prazos e motivos obrigatórios).
- **Substituição**: operação para substituir NFS-e (quando suportada).

## 3) Matriz de requisitos por município (preencher após validação)

| Município | Campos obrigatórios (RPS/NFS-e) | Códigos de serviço | Alíquotas ISS | Regras de retenção | CNAE |
| --- | --- | --- | --- | --- | --- |
| Belo Horizonte (MG) | **a confirmar** | **a confirmar** | **a confirmar** | **a confirmar** | **a confirmar** |
| Orlândia (SP) | **a confirmar** | **a confirmar** | **a confirmar** | **a confirmar** | **a confirmar** |

## 4) Próximos passos sugeridos

1. **Acessar o portal NFS-e** de cada município e localizar a seção de “Web Service”/“Integração”.
2. **Baixar o manual técnico** (layout RPS/XML) e **WSDL**.
3. Confirmar:
   - versão do layout (ABRASF ou própria),
   - assinatura digital exigida,
   - endpoints de homologação/produção,
   - regras de campos obrigatórios,
   - listas de serviços, alíquotas e retenções.
4. Substituir os campos “**a confirmar**” deste documento com as informações oficiais.

## 4.1) Evento de negócio para emissão

- **Evento gatilho**: a NFS-e é criada quando a consulta é finalizada (status `finalizada`).
- A emissão fica em fila e pode ser processada de forma assíncrona dependendo do município configurado.

## 5) Modelagem de dados e relacionamento com Clinica

As tabelas de NFS-e são relacionais e referenciam a clínica emissora via `clinica_id`:

- **`nfse_issues`**: registro principal por emissão (RPS/NFS-e), com status, protocolo, dados de tomador/prestador, valores e campos de cancelamento/substituição. Relaciona-se com `Clinica` por `clinica_id`.
- **`nfse_events`**: histórico de eventos por NFS-e (ex.: envio, autorização, cancelamento), com `nfse_issue_id` e `clinica_id` para vincular ao registro principal e à clínica.
- **`nfse_xmls`**: armazenamento de XMLs de envio/retorno por emissão, vinculados a `nfse_issue_id` e `clinica_id` para rastreabilidade completa da clínica e da nota.

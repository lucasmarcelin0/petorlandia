# 🔐 Segurança de credenciais NFS-e

Este documento descreve a política de acesso e o processo de rotação da chave mestra usada
para criptografar credenciais NFS-e (usuário, senha, certificado, token).

## Objetivo

- Garantir que credenciais sensíveis não fiquem em claro no banco.
- Permitir rotação de chave com backfill controlado.
- Evitar exposição acidental de segredos em logs.

## Chave mestra (`FISCAL_MASTER_KEY`)

- Deve ser definida como variável de ambiente com valor forte e único.
- A chave é derivada internamente e usada para criptografia simétrica.
- Sem a chave, a aplicação não consegue descriptografar credenciais armazenadas.

## Política de acesso

- **Somente** serviços e administradores que precisam emitir NFS-e devem ter acesso
  à variável `FISCAL_MASTER_KEY`.
- O valor da chave **não deve** ser armazenado em repositório, arquivos `.env` versionados,
  nem enviado por canais inseguros.
- Rotinas de suporte devem evitar imprimir credenciais em logs ou mensagens de erro.

## Rotação de chave

1. **Agendar janela de manutenção**: durante a rotação, emissões de NFS-e devem ser pausadas.
2. **Gerar nova chave** e armazená-la no cofre de segredos com controle de acesso.
3. **Aplicar a nova chave** no ambiente (atualizando `FISCAL_MASTER_KEY`).
4. **Executar backfill** para recriptografar credenciais já existentes:

   ```bash
   python scripts/nfse_encrypt_backfill.py
   ```

5. **Validar operação** com emissão de NFS-e em ambiente de teste.
6. **Revogar chave anterior** no cofre de segredos.

## Backfill de credenciais existentes

- O script `scripts/nfse_encrypt_backfill.py` é idempotente e ignora valores já criptografados.
- Utilize `--dry-run` para validar impacto antes de persistir alterações.
- Em caso de falha por chave ausente, configure `FISCAL_MASTER_KEY` e execute novamente.

## Boas práticas adicionais

- Evitar salvar credenciais em variáveis globais por longos períodos.
- Monitorar acessos à variável de ambiente e auditar mudanças.
- Revisar permissões de usuários administrativos periodicamente.

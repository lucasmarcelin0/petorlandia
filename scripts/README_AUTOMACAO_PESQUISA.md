# Automação visual da pesquisa de rações

Agora a automação principal está em Python:

- Script principal: [automacao_pesquisa_whatsapp.py](C:\Users\lucas\petorlandia\petorlandia\scripts\automacao_pesquisa_whatsapp.py)

O arquivo `.ahk` antigo ficou apenas como referência e não deve ser executado com `python`.

## O que esse script faz

Ele automatiza o fluxo de tela usando:

- captura visual do botão
- busca do botão na tela inteira
- clique automático
- fallback para ponto salvo, caso a busca visual não encontre com confiança suficiente

## Fluxos disponíveis

Fluxo normal:

```powershell
python scripts/automacao_pesquisa_whatsapp.py run sent
```

Fluxo de exceção:

```powershell
python scripts/automacao_pesquisa_whatsapp.py run do-not-send
```

## Como calibrar

Você precisa calibrar 5 alvos visuais.

Rode um comando por vez:

```powershell
python scripts/automacao_pesquisa_whatsapp.py calibrate send_pesquisa
python scripts/automacao_pesquisa_whatsapp.py calibrate whatsapp_send
python scripts/automacao_pesquisa_whatsapp.py calibrate site_tab
python scripts/automacao_pesquisa_whatsapp.py calibrate mark_sent
python scripts/automacao_pesquisa_whatsapp.py calibrate do_not_send
```

Em cada calibragem:

1. deixe a tela no estado certo
2. coloque o mouse no centro do botão
3. pressione `Enter` no terminal
4. o script vai salvar uma imagem-modelo daquele botão

Os templates ficam em:

- pasta: `scripts/automacao_pesquisa_templates`

E a configuração fica em:

- arquivo: `scripts/automacao_pesquisa_whatsapp.json`

## Uso recomendado

### Para envio normal

Deixe o tutor atual visível na tela e rode:

```powershell
python scripts/automacao_pesquisa_whatsapp.py run sent
```

Sequência:

1. clica em `Enviar pesquisa`
2. espera abrir a aba do WhatsApp
3. clica em `Enviar`
4. volta para a aba do site
5. clica em `Marcar como enviado`

### Para número que não foi

```powershell
python scripts/automacao_pesquisa_whatsapp.py run do-not-send
```

Sequência:

1. volta para a aba do site
2. clica em `Não enviar por agora`

## Verificar o que já foi calibrado

```powershell
python scripts/automacao_pesquisa_whatsapp.py status
```

## Observações importantes

- mantenha o navegador no mesmo zoom e tamanho de janela
- se a aparência do botão mudar muito, recalibre
- a busca visual é mais inteligente do que coordenada fixa, mas não faz milagres se a tela estiver muito diferente
- se o WhatsApp demorar mais no seu PC, podemos aumentar os delays no arquivo JSON

## Próximo passo possível

Se essa versão funcionar bem, o próximo refinamento é adicionar:

- repetição em lote
- tecla de emergência para abortar
- confirmação visual antes do clique
- limitação da busca a uma região da tela para ficar mais rápida

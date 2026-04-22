#Requires AutoHotkey v2.0
#SingleInstance Force

coordFile := A_ScriptDir . "\automacao_pesquisa_whatsapp.ini"

global delayAfterOpenWhatsapp := 900
global delayBeforeSend := 500
global delayAfterSend := 700
global delayAfterReturn := 500
global delayAfterStatus := 1600

EnsureConfigFile()

F8::RunHappyPath()
F9::RunDoNotSendPath()
F6::CaptureCurrentMouse("send_pesquisa")
F7::CaptureCurrentMouse("whatsapp_send")
^F6::CaptureCurrentMouse("site_tab")
^F7::CaptureCurrentMouse("mark_sent")
^F8::CaptureCurrentMouse("do_not_send")

F1::ShowInstructions()

RunHappyPath() {
    if !HasRequiredCoords(["send_pesquisa", "whatsapp_send", "site_tab", "mark_sent"]) {
        return
    }

    ClickSavedPoint("send_pesquisa")
    Sleep delayAfterOpenWhatsapp

    ClickSavedPoint("whatsapp_send")
    Sleep delayAfterSend

    ClickSavedPoint("site_tab")
    Sleep delayAfterReturn

    ClickSavedPoint("mark_sent")
    Sleep delayAfterStatus
}

RunDoNotSendPath() {
    if !HasRequiredCoords(["site_tab", "do_not_send"]) {
        return
    }

    ClickSavedPoint("site_tab")
    Sleep delayAfterReturn

    ClickSavedPoint("do_not_send")
    Sleep delayAfterStatus
}

ShowInstructions() {
    message :=
    (
    Automacao da pesquisa de racoes

    Hotkeys principais:
    F8  -> fluxo normal
    F9  -> marcar "Nao enviar por agora"

    Calibragem:
    F6   -> salva posicao do botao "Enviar pesquisa"
    F7   -> salva posicao do botao "Enviar" no WhatsApp
    Ctrl+F6 -> salva posicao da aba do site
    Ctrl+F7 -> salva posicao do botao "Marcar como enviado"
    Ctrl+F8 -> salva posicao do botao "Nao enviar por agora"

    Uso:
    1. Deixe o navegador sempre no mesmo lugar da tela.
    2. Passe o mouse sobre cada botao e use as teclas de calibragem.
    3. Na rotina normal, com o tutor atual aberto, pressione F8.
    4. Se o numero falhar, pressione F9.
    )
    MsgBox message, "Automacao Pesquisa WhatsApp"
}

CaptureCurrentMouse(key) {
    MouseGetPos &x, &y
    IniWrite x, coordFile, "coords", key . "_x"
    IniWrite y, coordFile, "coords", key . "_y"
    ToolTip "Salvo: " . key . " -> " . x . ", " . y
    Sleep 900
    ToolTip
}

ClickSavedPoint(key) {
    x := Integer(IniRead(coordFile, "coords", key . "_x", ""))
    y := Integer(IniRead(coordFile, "coords", key . "_y", ""))
    MouseMove x, y, 0
    Sleep 120
    Click
}

HasRequiredCoords(keys) {
    missing := []
    for key in keys {
        x := IniRead(coordFile, "coords", key . "_x", "")
        y := IniRead(coordFile, "coords", key . "_y", "")
        if (x = "" || y = "") {
            missing.Push(key)
        }
    }

    if missing.Length {
        MsgBox "Faltam coordenadas salvas para:`n- " . JoinLines(missing), "Automacao Pesquisa WhatsApp"
        return false
    }
    return true
}

JoinLines(items) {
    text := ""
    for index, item in items {
        text .= item
        if (index < items.Length) {
            text .= "`n- "
        }
    }
    return text
}

EnsureConfigFile() {
    if !FileExist(coordFile) {
        IniWrite "", coordFile, "coords", "send_pesquisa_x"
        IniWrite "", coordFile, "coords", "send_pesquisa_y"
        IniWrite "", coordFile, "coords", "whatsapp_send_x"
        IniWrite "", coordFile, "coords", "whatsapp_send_y"
        IniWrite "", coordFile, "coords", "site_tab_x"
        IniWrite "", coordFile, "coords", "site_tab_y"
        IniWrite "", coordFile, "coords", "mark_sent_x"
        IniWrite "", coordFile, "coords", "mark_sent_y"
        IniWrite "", coordFile, "coords", "do_not_send_x"
        IniWrite "", coordFile, "coords", "do_not_send_y"
    }
}

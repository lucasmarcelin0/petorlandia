(() => {
  "use strict";

  const $ = (selector) => document.querySelector(selector);
  const lobby = $("#lobby");
  const callRoom = $("#callRoom");
  const startButton = $("#startCall");
  const localVideo = $("#localVideo");
  const localScreenVideo = $("#localScreenVideo");
  const remoteVideo = $("#remoteVideo");
  const remotePlaceholder = $("#remotePlaceholder");
  const waitingTitle = $("#waitingTitle");
  const waitingText = $("#waitingText");
  const connectionBadge = $("#connectionBadge");
  const inviteInput = $("#inviteLink");
  const roomCodeTop = $("#roomCodeTop");
  const videoStage = $(".video-stage");
  const localTile = $("#localTile");
  const enableMediaButton = $("#enableMedia");
  const micButton = $("#toggleMic");
  const cameraButton = $("#toggleCamera");
  const shareButton = $("#shareScreen");
  const focusRemoteButton = $("#focusRemote");
  const focusLocalButton = $("#focusLocal");
  const mediaHelp = $("#mediaHelp");
  const mediaHelpTitle = $("#mediaHelpTitle");
  const mediaHelpText = $("#mediaHelpText");
  const retryMediaButton = $("#retryMedia");
  const chatMessages = $("#chatMessages");
  const chatEmpty = $("#chatEmpty");
  const chatForm = $("#chatForm");
  const chatInput = $("#chatInput");
  const reliableCallLink = $("#reliableCallLink");
  const toast = $("#toast");
  const ROOM_ASSET_VERSION = "20260811d";

  const sanitizeRoom = (value) => (value || "")
    .toString()
    .replace(/[^a-z0-9_-]/gi, "")
    .slice(0, 48)
    .toUpperCase();

  const makeRoomCode = () => {
    if (window.crypto?.getRandomValues) {
      const values = new Uint8Array(8);
      window.crypto.getRandomValues(values);
      return Array.from(values, (value) => value.toString(36).padStart(2, "0")).join("").slice(0, 12).toUpperCase();
    }
    return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`.slice(0, 12).toUpperCase();
  };

  const pageUrl = new URL(window.location.href);
  let roomCode = sanitizeRoom(pageUrl.searchParams.get("sala"));
  let pageUrlChanged = false;
  if (!roomCode) {
    roomCode = makeRoomCode();
    pageUrl.searchParams.set("sala", roomCode);
    pageUrlChanged = true;
  }
  if (pageUrl.searchParams.get("v") !== ROOM_ASSET_VERSION) {
    pageUrl.searchParams.set("v", ROOM_ASSET_VERSION);
    pageUrlChanged = true;
  }
  if (pageUrlChanged) window.history.replaceState(null, "", pageUrl.toString());
  const inviteUrl = pageUrl.toString();
  const reliableRoomName = `PetOrlandiaSalaADois-${roomCode}`;
  const reliableCallUrl = `https://meet.jit.si/${encodeURIComponent(reliableRoomName)}`;
  roomCodeTop.textContent = roomCode;
  inviteInput.value = inviteUrl;
  reliableCallLink.href = reliableCallUrl;

  const baseIceServers = [
    { urls: ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"] },
  ];

  const state = {
    socket: null,
    peer: null,
    localStream: null,
    cameraTrack: null,
    screenTrack: null,
    screenStream: null,
    screenSender: null,
    pendingCandidates: [],
    seat: null,
    participants: 0,
    ended: false,
    spotlight: "remote",
    spotlightChosen: false,
    mediaRequestInFlight: false,
    iceServers: baseIceServers,
    relayAvailable: false,
    iceRestarted: false,
    relayForced: false,
    relayCandidateFound: false,
    relayTimer: null,
  };

  const showToast = (message) => {
    toast.textContent = message;
    toast.classList.add("show");
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => toast.classList.remove("show"), 2400);
  };

  const setConnectionStatus = (message, live = false) => {
    connectionBadge.textContent = message;
    connectionBadge.classList.toggle("is-live", live);
  };

  const appendChatMessage = (message, { mine = false, system = false } = {}) => {
    const text = String(message || "").trim();
    if (!text) return;
    chatEmpty.hidden = true;
    const bubble = document.createElement("div");
    bubble.className = `chat-message${mine ? " is-mine" : ""}${system ? " is-system" : ""}`;
    bubble.textContent = text;
    chatMessages.appendChild(bubble);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  };

  const setSpotlight = (target, chosenByUser = false) => {
    const local = target === "local";
    const localScreen = local && Boolean(state.screenStream);
    state.spotlight = local ? "local" : "remote";
    if (chosenByUser) state.spotlightChosen = true;
    videoStage.classList.toggle("is-local-featured", local && !localScreen);
    videoStage.classList.toggle("is-local-screen-featured", localScreen);
    focusLocalButton.setAttribute("aria-pressed", String(local));
    focusRemoteButton.setAttribute("aria-pressed", String(!local));
  };

  const hideMediaHelp = () => {
    mediaHelp.hidden = true;
  };

  const showMediaHelp = (message, title = "Precisamos liberar a câmera e o microfone") => {
    mediaHelpTitle.textContent = title;
    mediaHelpText.textContent = message;
    mediaHelp.hidden = false;
  };

  const setMediaRequestState = (loading) => {
    state.mediaRequestInFlight = loading;
    enableMediaButton.disabled = loading;
    if (loading) {
      enableMediaButton.innerHTML = "⏳ <span>Solicitando permissão…</span>";
    } else if (!state.localStream) {
      enableMediaButton.innerHTML = "🎙️ <span>Liberar câmera e microfone</span>";
    }
  };

  const toBase64 = (buffer) => {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    bytes.forEach((value) => { binary += String.fromCharCode(value); });
    return window.btoa(binary);
  };

  const prepareIceServers = async () => {
    if (!window.crypto?.subtle || state.relayAvailable) return;
    try {
      const username = `${Math.floor(Date.now() / 1000) + 3600}:petorlandia`;
      const key = await window.crypto.subtle.importKey(
        "raw",
        new TextEncoder().encode("openrelayprojectsecret"),
        { name: "HMAC", hash: "SHA-1" },
        false,
        ["sign"],
      );
      const signature = await window.crypto.subtle.sign("HMAC", key, new TextEncoder().encode(username));
      state.iceServers = [
        ...baseIceServers,
        {
          urls: [
            "turn:staticauth.openrelay.metered.ca:80?transport=udp",
            "turn:staticauth.openrelay.metered.ca:443?transport=tcp",
            "turns:staticauth.openrelay.metered.ca:443?transport=tcp",
          ],
          username,
          credential: toBase64(signature),
        },
      ];
      state.relayAvailable = true;
    } catch (error) {
      console.warn("Não foi possível preparar a rota de reserva da chamada", error);
    }
  };

  const copyInvite = async () => {
    try {
      await navigator.clipboard.writeText(inviteUrl);
    } catch (_) {
      inviteInput.focus();
      inviteInput.select();
      document.execCommand("copy");
      inviteInput.setSelectionRange(0, 0);
    }
    showToast("Convite copiado 💗");
  };

  const closePeer = () => {
    window.clearTimeout(state.relayTimer);
    state.relayTimer = null;
    state.relayForced = false;
    state.iceRestarted = false;
    state.relayCandidateFound = false;
    if (state.peer) {
      state.peer.ontrack = null;
      state.peer.onicecandidate = null;
      state.peer.close();
      state.peer = null;
    }
    state.pendingCandidates = [];
    remoteVideo.srcObject = null;
    remoteVideo.classList.remove("is-screen");
    remotePlaceholder.hidden = false;
  };

  const ensurePeer = () => {
    if (state.peer && state.peer.connectionState !== "closed") return state.peer;

    const peer = new RTCPeerConnection({ iceServers: state.iceServers });
    state.peer = peer;

    state.localStream?.getTracks().forEach((track) => {
      if (track.kind !== "video" || !state.screenTrack) peer.addTrack(track, state.localStream);
    });
    if (state.screenTrack && state.screenStream) {
      state.screenSender = peer.addTrack(state.screenTrack, state.screenStream);
    }
    peer.onicecandidate = ({ candidate }) => {
      if (candidate && state.socket?.connected) {
        if (candidate.candidate.includes(" typ relay ")) state.relayCandidateFound = true;
        state.socket.emit("webrtc_signal", { candidate: candidate.toJSON() });
      }
    };
    peer.ontrack = (event) => {
      const [stream] = event.streams;
      if (stream) remoteVideo.srcObject = stream;
      remotePlaceholder.hidden = true;
      remoteVideo.play().catch(() => {});
    };
    peer.onconnectionstatechange = () => {
      const status = peer.connectionState;
      if (status === "connected") {
        window.clearTimeout(state.relayTimer);
        setConnectionStatus("Vocês estão juntinhos", true);
        remotePlaceholder.hidden = true;
        appendChatMessage("Chamada de áudio e vídeo conectada.", { system: true });
      } else if (status === "connecting") {
        setConnectionStatus("Aproximando vocês…");
      } else if (status === "failed") {
        setConnectionStatus("A conexão falhou");
        waitingTitle.textContent = "Não conseguimos completar a chamada";
        waitingText.textContent = "A rota direta não fechou. Cliquem em “Abrir vídeo estável agora” abaixo; o mesmo botão leva vocês à mesma sala.";
        remotePlaceholder.hidden = false;
        appendChatMessage("O vídeo não conectou, mas as mensagens continuam funcionando.", { system: true });
      } else if (status === "disconnected") {
        setConnectionStatus("Reconectando…");
      }
    };
    peer.oniceconnectionstatechange = () => {
      if (peer.iceConnectionState === "failed") forceRelayConnection().catch(() => {});
    };
    window.clearTimeout(state.relayTimer);
    state.relayTimer = window.setTimeout(() => {
      if (!["connected", "completed"].includes(peer.iceConnectionState)) {
        forceRelayConnection().catch(() => {});
      }
    }, 8000);
    return peer;
  };

  const sendOffer = async ({ iceRestart = false } = {}) => {
    const peer = ensurePeer();
    if (!state.socket?.connected || peer.signalingState !== "stable") return;
    const offer = await peer.createOffer({ iceRestart });
    await peer.setLocalDescription(offer);
    state.socket.emit("webrtc_signal", { description: peer.localDescription });
  };

  const forceRelayConnection = async () => {
    const peer = state.peer;
    if (!peer || state.relayForced || !state.relayAvailable) return;
    state.relayForced = true;
    state.iceRestarted = true;
    setConnectionStatus("Conectando pelo servidor de apoio…");
    showToast("Tentando uma rota mais compatível com as duas redes");
    peer.setConfiguration({ iceServers: state.iceServers, iceTransportPolicy: "relay" });
    if (state.seat === 1 && peer.signalingState === "stable") await sendOffer({ iceRestart: true });
  };

  const renegotiate = async () => {
    if (state.participants >= 2) await sendOffer();
  };

  const flushCandidates = async () => {
    while (state.pendingCandidates.length && state.peer?.remoteDescription) {
      const candidate = state.pendingCandidates.shift();
      await state.peer.addIceCandidate(candidate);
    }
  };

  const handleSignal = async (payload) => {
    try {
      const peer = ensurePeer();
      if (payload.description) {
        const description = payload.description;
        if (description.type === "offer") {
          if (peer.signalingState !== "stable") await peer.setLocalDescription({ type: "rollback" });
          await peer.setRemoteDescription(description);
          await flushCandidates();
          const answer = await peer.createAnswer();
          await peer.setLocalDescription(answer);
          state.socket.emit("webrtc_signal", { description: peer.localDescription });
          if (state.screenTrack) await renegotiate();
        } else if (description.type === "answer" && peer.signalingState === "have-local-offer") {
          await peer.setRemoteDescription(description);
          await flushCandidates();
        }
      } else if (payload.candidate) {
        if (peer.remoteDescription) await peer.addIceCandidate(payload.candidate);
        else state.pendingCandidates.push(payload.candidate);
      }
    } catch (error) {
      console.error("Falha ao negociar a videochamada", error);
      setConnectionStatus("Tentando reconectar…");
    }
  };

  const updateWaitingState = () => {
    if (state.participants < 2) {
      waitingTitle.textContent = "Esperando seu amor chegar";
      waitingText.textContent = "Copie o convite acima e envie. A chamada começa automaticamente quando ela entrar.";
      remotePlaceholder.hidden = false;
      setConnectionStatus("Esperando companhia");
    }
  };

  const connectSocket = () => {
    if (typeof window.io !== "function") throw new Error("Não foi possível carregar a conexão em tempo real.");
    const socket = window.io("/chamada", {
      query: { sala: roomCode },
      transports: ["websocket", "polling"],
    });
    state.socket = socket;

    socket.on("room_state", (payload) => {
      state.seat = Number(payload.seat);
      state.participants = Number(payload.participants) || 0;
      updateWaitingState();
    });
    socket.on("presence", ({ participants }) => {
      state.participants = Number(participants) || 0;
      updateWaitingState();
    });
    socket.on("peer_joined", async ({ participants }) => {
      state.participants = Number(participants) || 2;
      setConnectionStatus("Conectando vocês…");
      waitingTitle.textContent = "Ela chegou 💗";
      waitingText.textContent = "Só mais um instante para conectar o vídeo.";
      appendChatMessage("Sua companhia entrou na sala.", { system: true });
      if (state.screenTrack) state.socket.emit("screen_share_state", { active: true });
      if (state.seat === 1) await sendOffer();
    });
    socket.on("webrtc_signal", handleSignal);
    socket.on("chat_message", ({ message, sender }) => {
      appendChatMessage(message, { mine: Number(sender) === state.seat });
    });
    socket.on("screen_share_state", ({ active }) => {
      remoteVideo.classList.toggle("is-screen", active === true);
      if (active) {
        if (!state.spotlightChosen) setSpotlight("remote");
        showToast("A outra tela está sendo compartilhada");
      }
    });
    socket.on("peer_left", async ({ participants }) => {
      state.participants = Number(participants) || 1;
      if (state.screenTrack) await stopScreenShare();
      closePeer();
      waitingTitle.textContent = "Sua companhia saiu da sala";
      waitingText.textContent = "O mesmo convite continua funcionando caso ela queira voltar.";
      setConnectionStatus("Esperando companhia");
      appendChatMessage("Sua companhia saiu da sala.", { system: true });
    });
    socket.on("room_full", ({ message }) => {
      showToast(message || "Esta sala já está cheia.");
      setConnectionStatus("Sala cheia");
    });
    socket.on("connect_error", (error) => {
      const message = error?.data?.message || error?.message || "Não foi possível entrar na sala.";
      setConnectionStatus("Falha ao entrar");
      waitingTitle.textContent = "Não conseguimos abrir a sala";
      waitingText.textContent = message;
      remotePlaceholder.hidden = false;
    });
    socket.on("disconnect", (reason) => {
      if (!state.ended && reason !== "io client disconnect") setConnectionStatus("Reconectando…");
    });
  };

  const getLocalTrack = (kind) => state.localStream?.getTracks().find((track) => track.kind === kind) || null;

  const updateMediaControls = () => {
    const hasAudio = Boolean(getLocalTrack("audio"));
    const hasVideo = Boolean(getLocalTrack("video"));
    micButton.hidden = !hasAudio;
    cameraButton.hidden = !hasVideo;
    enableMediaButton.hidden = hasAudio && hasVideo;
    if (!enableMediaButton.hidden && !state.mediaRequestInFlight) {
      const missing = [!hasVideo && "câmera", !hasAudio && "microfone"].filter(Boolean).join(" e ");
      enableMediaButton.innerHTML = `🎙️ <span>Liberar ${missing}</span>`;
    }
  };

  const describeMediaFailures = (failures) => {
    const devices = failures.map(({ kind }) => kind === "video" ? "a câmera" : "o microfone").join(" e ");
    const errorNames = failures.map(({ error }) => error?.name);
    if (errorNames.every((name) => name === "NotAllowedError" || name === "PermissionDeniedError")) {
      return `${devices} foi bloqueado. Se o cadeado do Chrome já estiver em “Permitir”, abra Configurações do Windows > Privacidade e segurança > Câmera e Microfone e habilite o acesso para aplicativos de desktop (Chrome).`;
    }
    if (errorNames.some((name) => name === "NotFoundError")) {
      return `Não encontramos ${devices}. Conecte o dispositivo e confirme se ele aparece nas configurações do Windows.`;
    }
    if (errorNames.some((name) => name === "NotReadableError" || name === "TrackStartError")) {
      return `${devices} está sendo usado por outro aplicativo. Feche Zoom, Meet, Teams ou outro programa que possa estar usando o dispositivo.`;
    }
    return `Não foi possível ativar ${devices}. Tente fechar outros aplicativos e usar “Tentar novamente”.`;
  };

  const requestLocalMedia = async () => {
    const hasAudio = Boolean(getLocalTrack("audio"));
    const hasVideo = Boolean(getLocalTrack("video"));
    if (hasAudio && hasVideo) return state.localStream;
    if (state.mediaRequestInFlight) return null;
    setMediaRequestState(true);
    hideMediaHelp();
    try {
      if (!window.isSecureContext && !["localhost", "127.0.0.1"].includes(window.location.hostname)) {
        throw new Error("A videochamada precisa ser aberta por HTTPS para acessar câmera e microfone.");
      }
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("Este navegador não oferece acesso à câmera e ao microfone.");
      }
      const missingKinds = [
        !hasVideo && { kind: "video", constraints: { video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: "user" } } },
        !hasAudio && { kind: "audio", constraints: { audio: { echoCancellation: true, noiseSuppression: true } } },
      ].filter(Boolean);
      const acquiredTracks = [];
      const failures = [];
      for (const request of missingKinds) {
        try {
          const stream = await navigator.mediaDevices.getUserMedia(request.constraints);
          acquiredTracks.push(...stream.getTracks());
        } catch (error) {
          failures.push({ kind: request.kind, error });
        }
      }
      if (!acquiredTracks.length) throw failures[0]?.error || new Error("Não foi possível acessar câmera e microfone.");
      if (!state.localStream) state.localStream = new MediaStream();
      acquiredTracks.forEach((track) => state.localStream.addTrack(track));
      state.cameraTrack = getLocalTrack("video");
      localVideo.srcObject = state.localStream;
      updateMediaControls();
      if (state.peer) {
        acquiredTracks.forEach((track) => {
          if (track.kind !== "video" || !state.screenTrack) {
            state.peer.addTrack(track, state.localStream);
          }
        });
        await renegotiate();
      }
      if (failures.length) {
        const message = describeMediaFailures(failures);
        showMediaHelp(message, "Ativamos um dispositivo; falta liberar o outro");
        showToast("Um dispositivo foi ativado; veja abaixo o que falta liberar");
      } else {
        hideMediaHelp();
        showToast("Câmera e microfone ativados");
      }
      return state.localStream;
    } catch (error) {
      const denied = error?.name === "NotAllowedError" || error?.name === "PermissionDeniedError";
      const message = describeMediaFailures([{ kind: "video", error }, { kind: "audio", error }]);
      showMediaHelp(message, denied ? "A permissão está bloqueada no navegador" : "Não foi possível ativar os dispositivos");
      showToast(denied ? "Permissão bloqueada — veja como liberar abaixo" : message);
      throw error;
    } finally {
      if (!state.localStream) setMediaRequestState(false);
    }
  };

  const startRoom = async () => {
    startButton.disabled = true;
    startButton.innerHTML = "Preparando conexão <span>…</span>";
    try {
      await prepareIceServers();
      lobby.hidden = true;
      callRoom.hidden = false;
      updateMediaControls();
      hideMediaHelp();
      state.spotlightChosen = false;
      setSpotlight("remote");
      connectSocket();
    } catch (error) {
      lobby.hidden = false;
      callRoom.hidden = true;
      startButton.disabled = false;
      startButton.innerHTML = "Entrar na sala <span>→</span>";
      showToast(error.message || "Não foi possível entrar na sala.");
    }
  };

  const toggleTrack = (kind, button) => {
    const track = state.localStream?.getTracks().find((item) => item.kind === kind && item !== state.screenTrack);
    if (!track) return;
    track.enabled = !track.enabled;
    const off = !track.enabled;
    button.classList.toggle("is-off", off);
    button.setAttribute("aria-pressed", String(off));
    button.firstChild.textContent = kind === "audio" ? (off ? "🔇 " : "🎙️ ") : (off ? "🚫 " : "📹 ");
    showToast(`${kind === "audio" ? "Microfone" : "Câmera"} ${off ? "desligado" : "ligada"}`);
  };

  const stopScreenShare = async () => {
    if (!state.screenTrack) return;
    state.screenTrack.onended = null;
    state.screenTrack.stop();
    state.screenTrack = null;
    const sender = state.screenSender || state.peer?.getSenders().find((item) => item.track?.kind === "video");
    if (sender && state.cameraTrack) {
      await sender.replaceTrack(state.cameraTrack);
    } else if (sender && state.peer) {
      state.peer.removeTrack(sender);
      await renegotiate();
    }
    state.screenStream = null;
    state.screenSender = null;
    localScreenVideo.srcObject = null;
    localVideo.srcObject = state.localStream;
    localTile.classList.remove("is-sharing");
    setSpotlight(state.spotlight);
    shareButton.classList.remove("is-active");
    shareButton.setAttribute("aria-pressed", "false");
    shareButton.firstChild.textContent = "🖥️ ";
    state.socket?.emit("screen_share_state", { active: false });
    showToast("Compartilhamento encerrado");
  };

  const toggleScreenShare = async () => {
    if (state.screenTrack) {
      await stopScreenShare();
      return;
    }
    try {
      if (!navigator.mediaDevices?.getDisplayMedia) throw new Error("Seu navegador não permite compartilhar a tela.");
      const displayStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
      const screenTrack = displayStream.getVideoTracks()[0];
      const peer = ensurePeer();
      let sender = peer.getSenders().find((item) => item.track?.kind === "video");
      const needsNegotiation = !sender;
      if (sender) await sender.replaceTrack(screenTrack);
      else sender = peer.addTrack(screenTrack, displayStream);
      state.screenTrack = screenTrack;
      state.screenStream = displayStream;
      state.screenSender = sender;
      localScreenVideo.srcObject = displayStream;
      localVideo.srcObject = state.localStream;
      setSpotlight("local");
      shareButton.classList.add("is-active");
      shareButton.setAttribute("aria-pressed", "true");
      shareButton.firstChild.textContent = "⏹️ ";
      screenTrack.onended = stopScreenShare;
      state.socket?.emit("screen_share_state", { active: true });
      if (needsNegotiation) await renegotiate();
      showToast("Sua tela está sendo compartilhada");
    } catch (error) {
      if (error.name !== "NotAllowedError") showToast(error.message || "Não foi possível compartilhar a tela.");
    }
  };

  const endCall = () => {
    state.ended = true;
    if (state.screenTrack) {
      state.screenTrack.onended = null;
      state.screenTrack.stop();
    }
    state.localStream?.getTracks().forEach((track) => track.stop());
    state.socket?.disconnect();
    closePeer();
    localVideo.srcObject = null;
    localScreenVideo.srcObject = null;
    callRoom.hidden = true;
    lobby.hidden = false;
    startButton.disabled = false;
    startButton.innerHTML = "Entrar novamente <span>→</span>";
    state.localStream = null;
    state.cameraTrack = null;
    state.screenTrack = null;
    state.screenStream = null;
    state.screenSender = null;
    state.socket = null;
    state.ended = false;
    state.iceRestarted = false;
    state.relayForced = false;
    state.relayCandidateFound = false;
    window.clearTimeout(state.relayTimer);
    state.relayTimer = null;
    state.spotlightChosen = false;
    updateMediaControls();
    hideMediaHelp();
    setSpotlight("remote");
    showToast("Chamada encerrada");
  };

  startButton.addEventListener("click", startRoom);
  enableMediaButton.addEventListener("click", () => { requestLocalMedia().catch(() => {}); });
  retryMediaButton.addEventListener("click", () => { requestLocalMedia().catch(() => {}); });
  focusRemoteButton.addEventListener("click", () => setSpotlight("remote", true));
  focusLocalButton.addEventListener("click", () => {
    if (!state.localStream && !state.screenStream) {
      showToast("Ative a câmera ou compartilhe a tela para colocá-la em destaque");
      return;
    }
    setSpotlight("local", true);
  });
  $("#copyInvite").addEventListener("click", copyInvite);
  micButton.addEventListener("click", () => toggleTrack("audio", micButton));
  cameraButton.addEventListener("click", () => toggleTrack("video", cameraButton));
  shareButton.addEventListener("click", toggleScreenShare);
  reliableCallLink.addEventListener("click", () => {
    appendChatMessage("Abrindo a sala de vídeo estável. Peça para sua companhia usar o mesmo botão.", { system: true });
    if (state.socket?.connected) {
      state.socket.emit("chat_message", { message: "Clique em “Abrir vídeo estável agora” para entrar comigo na chamada." });
    }
  });
  chatForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const message = chatInput.value.trim();
    if (!message) return;
    if (!state.socket?.connected) {
      showToast("Aguarde a sala terminar de conectar para enviar mensagens");
      return;
    }
    state.socket.emit("chat_message", { message });
    chatInput.value = "";
    chatInput.focus();
  });
  $("#hangUp").addEventListener("click", endCall);
  window.addEventListener("beforeunload", () => {
    state.localStream?.getTracks().forEach((track) => track.stop());
    state.screenTrack?.stop();
  });
})();

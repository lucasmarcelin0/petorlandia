(() => {
  "use strict";

  const $ = (selector) => document.querySelector(selector);
  const lobby = $("#lobby");
  const callRoom = $("#callRoom");
  const startButton = $("#startCall");
  const localVideo = $("#localVideo");
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
  const toast = $("#toast");

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
  if (!roomCode) {
    roomCode = makeRoomCode();
    pageUrl.searchParams.set("sala", roomCode);
    window.history.replaceState(null, "", pageUrl.toString());
  }
  const inviteUrl = `${window.location.origin}${window.location.pathname}?sala=${encodeURIComponent(roomCode)}`;
  roomCodeTop.textContent = roomCode;
  inviteInput.value = inviteUrl;

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

  const setSpotlight = (target, chosenByUser = false) => {
    const local = target === "local";
    state.spotlight = local ? "local" : "remote";
    if (chosenByUser) state.spotlightChosen = true;
    videoStage.classList.toggle("is-local-featured", local);
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

    const peer = new RTCPeerConnection({
      iceServers: [
        { urls: ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"] },
      ],
    });
    state.peer = peer;

    state.localStream?.getTracks().forEach((track) => peer.addTrack(track, state.localStream));
    if (state.screenTrack && state.screenStream) {
      state.screenSender = peer.addTrack(state.screenTrack, state.screenStream);
    }
    peer.onicecandidate = ({ candidate }) => {
      if (candidate && state.socket?.connected) {
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
        setConnectionStatus("Vocês estão juntinhos", true);
        remotePlaceholder.hidden = true;
      } else if (status === "connecting") {
        setConnectionStatus("Aproximando vocês…");
      } else if (status === "failed") {
        setConnectionStatus("A conexão falhou");
        waitingTitle.textContent = "Não conseguimos completar a chamada";
        waitingText.textContent = "Tentem trocar de rede ou recarregar a sala. Algumas redes exigem um servidor TURN.";
        remotePlaceholder.hidden = false;
      } else if (status === "disconnected") {
        setConnectionStatus("Reconectando…");
      }
    };
    return peer;
  };

  const sendOffer = async () => {
    const peer = ensurePeer();
    if (!state.socket?.connected || peer.signalingState !== "stable") return;
    const offer = await peer.createOffer();
    await peer.setLocalDescription(offer);
    state.socket.emit("webrtc_signal", { description: peer.localDescription });
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
      if (state.screenTrack) state.socket.emit("screen_share_state", { active: true });
      if (state.seat === 1) await sendOffer();
    });
    socket.on("webrtc_signal", handleSignal);
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

  const showMediaControls = (enabled) => {
    enableMediaButton.hidden = enabled;
    micButton.hidden = !enabled;
    cameraButton.hidden = !enabled;
  };

  const requestLocalMedia = async () => {
    if (state.localStream) return state.localStream;
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
      state.localStream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: "user" },
        audio: { echoCancellation: true, noiseSuppression: true },
      });
      state.cameraTrack = state.localStream.getVideoTracks()[0] || null;
      localVideo.srcObject = state.localStream;
      showMediaControls(true);
      hideMediaHelp();
      if (state.peer) {
        state.localStream.getTracks().forEach((track) => {
          if (track.kind !== "video" || !state.screenTrack) {
            state.peer.addTrack(track, state.localStream);
          }
        });
        await renegotiate();
      }
      return state.localStream;
    } catch (error) {
      const denied = error?.name === "NotAllowedError" || error?.name === "PermissionDeniedError";
      let message = error.message || "Não foi possível acessar câmera e microfone.";
      if (denied) {
        message = "O navegador bloqueou a câmera ou o microfone. Abra o cadeado ao lado do endereço, permita os dois e depois tente novamente.";
      } else if (error?.name === "NotFoundError") {
        message = "Não encontramos câmera ou microfone. Conecte um dispositivo e feche outros aplicativos que possam estar usando-o.";
      } else if (error?.name === "NotReadableError") {
        message = "A câmera ou o microfone já está em uso por outro aplicativo. Feche Zoom, Meet ou outro programa e tente novamente.";
      }
      showMediaHelp(message, denied ? "A permissão está bloqueada no navegador" : "Não foi possível ativar os dispositivos");
      showToast(denied ? "Permissão bloqueada — veja como liberar abaixo" : message);
      throw error;
    } finally {
      if (!state.localStream) setMediaRequestState(false);
    }
  };

  const startRoom = () => {
    startButton.disabled = true;
    try {
      lobby.hidden = true;
      callRoom.hidden = false;
      showMediaControls(false);
      hideMediaHelp();
      state.spotlightChosen = false;
      setSpotlight("remote");
      connectSocket();
    } catch (error) {
      lobby.hidden = false;
      callRoom.hidden = true;
      startButton.disabled = false;
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
    localVideo.srcObject = state.localStream;
    localTile.classList.remove("is-sharing");
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
      localVideo.srcObject = displayStream;
      setSpotlight("local");
      localTile.classList.add("is-sharing");
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
    state.spotlightChosen = false;
    showMediaControls(false);
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
  $("#hangUp").addEventListener("click", endCall);
  window.addEventListener("beforeunload", () => {
    state.localStream?.getTracks().forEach((track) => track.stop());
    state.screenTrack?.stop();
  });
})();

(() => {
  const sanitizeRoomCode = (value) =>
    (value || "")
      .toString()
      .replace(/[^a-z0-9_-]/gi, "")
      .slice(0, 32)
      .toUpperCase();

  const generateRoomCode = () => Math.random().toString(36).slice(2, 8).toUpperCase();

  const ensureRoomCode = () => {
    const url = new URL(window.location.href);
    const params = url.searchParams;
    const existing = sanitizeRoomCode(params.get("sala"));
    if (existing) {
      return existing;
    }

    const fresh = generateRoomCode();
    params.set("sala", fresh);
    url.search = params.toString();
    window.history.replaceState(null, "", url.toString());
    return fresh;
  };

  const roomCode = ensureRoomCode();

  const socket =
    typeof io === "function"
      ? io({
          query: { room: roomCode },
        })
      : null;
  const supportsSocket = Boolean(socket);

  const INITIAL_ROWS = [
    [true, true, true],
    [true, true, true],
    [true, true, true],
    [true, true],
    [true, true],
  ];

  const cloneRows = (rows) => rows.map((row) => row.slice());
  const createZeroArray = (length) => Array.from({ length }, () => 0);
  const isSplitRow = (row) =>
    Array.isArray(row) &&
    row.length === 3 &&
    Boolean(row[0]) &&
    Boolean(row[2]) &&
    !row[1];
  const computeAlternateRows = (rows) => rows.map((row) => isSplitRow(row));

  const randomColor = () => `hsl(${Math.floor(Math.random() * 360)}, 70%, 68%)`;
  const randomGradient = () => {
    const c1 = randomColor();
    const c2 = randomColor();
    return `radial-gradient(circle at top left, ${c1}, ${c2})`;
  };

  const randomEmoji = () => {
    const emojis = ["😺", "🐶", "🐹", "🦊", "🐸", "🐼", "🐵", "🐰", "🐯", "🐮"];
    return emojis[Math.floor(Math.random() * emojis.length)];
  };

  const DEFAULT_PLAYER_NAMES = ["Jogador 1", "Jogador 2"];

  const sanitizeName = (value, fallback) => {
    const text = (value || "").toString().trim();
    const collapsed = text.replace(/\s+/g, " ");
    const finalText = collapsed.slice(0, 40);
    if (!finalText) {
      return fallback;
    }
    return finalText;
  };

  const state = {
    rows: cloneRows(INITIAL_ROWS),
    turn: 1,
    startingPlayer: 1,
    winner: null,
    hasPlayed: false,
    activeRow: null,
    selectionRange: null,
    bgGradient: randomGradient(),
    stickColor: randomColor(),
    playerEmojis: [randomEmoji(), randomEmoji()],
    playerNames: DEFAULT_PLAYER_NAMES.slice(),
    lastTurn: null,
    turnOriginRows: cloneRows(INITIAL_ROWS),
    turnRemovalCount: 0,
    turnRowRemovalCounts: createZeroArray(INITIAL_ROWS.length),
    alternateRows: INITIAL_ROWS.map(() => false),
    ruleMessage: null,
    roomError: null,
    mode: supportsSocket ? "online" : "local",
    connection: supportsSocket && socket.connected ? "connected" : "connecting",
    mySeat: null,
  };

  const container = document.getElementById("root");
  if (!container) {
    return;
  }

  document.body.classList.add("game-body");

  // "← Arcade" é estático no HTML; o render() o encaixa no cabeçalho do jogo.
  const backLink = document.querySelector(".back-btn");

  // Reiniciar no meio da partida pede um segundo toque dentro deste prazo.
  const RESET_CONFIRM_MS = 3000;
  const RESET_LABEL = "↺ Reiniciar";
  const RESET_CONFIRM_LABEL = "Confirmar reinício";
  let resetArmedUntil = 0;
  let resetDisarmTimer = 0;

  const isOnlineMode = () => state.mode === "online" && supportsSocket;

  // No online o servidor só aceita jogadas de quem está na vez. Sem este aviso
  // o clique era desfeito pela resposta do servidor sem nenhuma explicação.
  const waitingForOpponent = () =>
    isOnlineMode() &&
    state.connection === "connected" &&
    (state.mySeat === 1 || state.mySeat === 2) &&
    state.turn !== state.mySeat;

  const currentTurnName = () =>
    sanitizeName(
      state.playerNames[state.turn - 1],
      DEFAULT_PLAYER_NAMES[state.turn - 1] || `Jogador ${state.turn}`
    );

  const setMode = (mode) => {
    if (mode === state.mode) {
      return;
    }
    if (mode === "online" && !supportsSocket) {
      return;
    }

    state.mode = mode;

    if (mode !== "online") {
      state.roomError = null;
    } else {
      emitState();
    }

    render();
  };

  const normalizeRows = (rows, fallbackRows = INITIAL_ROWS) => {
    const template = Array.isArray(fallbackRows)
      ? cloneRows(fallbackRows)
      : cloneRows(INITIAL_ROWS);
    if (!Array.isArray(rows)) {
      return template;
    }
    return template.map((templateRow, rowIndex) => {
      const sourceRow = Array.isArray(rows[rowIndex]) ? rows[rowIndex] : [];
      return templateRow.map((_, stickIndex) => {
        const value = sourceRow[stickIndex];
        if (typeof value === "boolean") {
          return value;
        }
        if (typeof value === "number") {
          return value !== 0;
        }
        return Boolean(value);
      });
    });
  };

  const ensureBaseline = () => {
    if (
      !Array.isArray(state.turnOriginRows) ||
      state.turnOriginRows.length !== state.rows.length
    ) {
      state.turnOriginRows = cloneRows(state.rows);
    }
  };

  const recalcTurnProgress = () => {
    const baseline = Array.isArray(state.turnOriginRows)
      ? state.turnOriginRows
      : [];
    const counts = [];
    let total = 0;

    state.rows.forEach((row, rowIndex) => {
      const baselineRow = Array.isArray(baseline[rowIndex])
        ? baseline[rowIndex]
        : [];
      let rowCount = 0;
      row.forEach((stick, stickIndex) => {
        if (baselineRow[stickIndex] && !stick) {
          rowCount += 1;
        }
      });
      counts[rowIndex] = rowCount;
      total += rowCount;
    });

    state.turnRowRemovalCounts = counts;
    state.turnRemovalCount = total;
  };

  const emitState = () => {
    if (!isOnlineMode()) {
      return;
    }

    socket.emit("move", {
      rows: cloneRows(state.rows).map((row) => row.map(Boolean)),
      turn: state.turn,
      winner: state.winner,
      players: {
        1: sanitizeName(state.playerNames[0], DEFAULT_PLAYER_NAMES[0]),
        2: sanitizeName(state.playerNames[1], DEFAULT_PLAYER_NAMES[1]),
      },
      starting_player: state.startingPlayer,
      has_played: Boolean(state.hasPlayed),
      active_row:
        typeof state.activeRow === "number" && Number.isFinite(state.activeRow)
          ? state.activeRow
          : null,
      bg_gradient: typeof state.bgGradient === "string" ? state.bgGradient : null,
      stick_color: typeof state.stickColor === "string" ? state.stickColor : null,
      player_emojis: Array.isArray(state.playerEmojis)
        ? state.playerEmojis.slice(0, 2).map((emoji) => `${emoji}`.slice(0, 8))
        : null,
    });
  };

  // ── Corte dos palitos: toque ou deslize (estilo Fruit Ninja) ─────────────

  const SWIPE_ACTIVATION_PX = 10;
  const STICK_HIT_SLOP_PX = 6;
  const TRAIL_LIFETIME_MS = 200;

  // Deslize em andamento. Os cortes feitos durante o gesto só vão para o
  // servidor quando o dedo sai da tela: com um envio por palito, a resposta do
  // primeiro chegava no meio do deslize, devolvia ao tabuleiro o palito recém
  // cortado e o servidor recusava o resto do corte como "restauração".
  let swipe = null;
  let suppressClickUntil = 0;

  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

  const prefersReducedMotion = () =>
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const showRuleMessage = (message) => {
    if (state.ruleMessage === message) {
      return;
    }
    state.ruleMessage = message;
    render();
  };

  // Camadas fixas fora do #root: o render() recria o tabuleiro a cada corte e
  // apagaria a animação no meio.
  let fxLayer = null;
  const ensureFxLayer = () => {
    if (!fxLayer || !fxLayer.isConnected) {
      fxLayer = document.createElement("div");
      fxLayer.className = "slice-fx";
      fxLayer.setAttribute("aria-hidden", "true");
      document.body.appendChild(fxLayer);
    }
    return fxLayer;
  };

  // Parte o palito em duas metades na linha do corte e as deixa cair.
  const playSliceEffect = (slice) => {
    if (!slice || !slice.rect || prefersReducedMotion()) {
      return;
    }
    const { rect } = slice;
    const width = rect.width;
    const height = rect.height;
    if (!width || !height) {
      return;
    }

    const localX = clamp(slice.x - rect.left, 0, width);
    const localY = clamp(slice.y - rect.top, height * 0.2, height * 0.8);
    const slope = Math.abs(slice.dx) > 0.01 ? clamp(slice.dy / slice.dx, -1.2, 1.2) : 0;
    const leftY = clamp(localY - localX * slope, 0, height);
    const rightY = clamp(localY + (width - localX) * slope, 0, height);
    const midY = (leftY + rightY) / 2;
    const side = slice.dx < 0 ? -1 : 1;

    const pieces = [
      {
        clip: `polygon(0 0, ${width}px 0, ${width}px ${rightY}px, 0 ${leftY}px)`,
        origin: `50% ${midY / 2}px`,
        frames: [
          { transform: "translate(0, 0) rotate(0deg)", opacity: 1, easing: "ease-out" },
          {
            transform: `translate(${side * 10}px, -16px) rotate(${-side * 16}deg)`,
            opacity: 1,
            offset: 0.3,
            easing: "ease-in",
          },
          { transform: `translate(${side * 24}px, 48px) rotate(${-side * 40}deg)`, opacity: 0 },
        ],
      },
      {
        clip: `polygon(0 ${leftY}px, ${width}px ${rightY}px, ${width}px ${height}px, 0 ${height}px)`,
        origin: `50% ${(midY + height) / 2}px`,
        frames: [
          { transform: "translate(0, 0) rotate(0deg)", opacity: 1, easing: "ease-out" },
          {
            transform: `translate(${-side * 6}px, 6px) rotate(${side * 12}deg)`,
            opacity: 1,
            offset: 0.3,
            easing: "ease-in",
          },
          { transform: `translate(${-side * 14}px, 66px) rotate(${side * 32}deg)`, opacity: 0 },
        ],
      },
    ];

    const layer = ensureFxLayer();
    pieces.forEach((piece) => {
      const pieceEl = document.createElement("div");
      if (typeof pieceEl.animate !== "function") {
        return;
      }
      pieceEl.className = "stick-piece";
      pieceEl.style.left = `${rect.left}px`;
      pieceEl.style.top = `${rect.top}px`;
      pieceEl.style.width = `${width}px`;
      pieceEl.style.height = `${height}px`;
      pieceEl.style.background = state.stickColor;
      pieceEl.style.clipPath = piece.clip;
      pieceEl.style.webkitClipPath = piece.clip;
      pieceEl.style.transformOrigin = piece.origin;
      layer.appendChild(pieceEl);
      const animation = pieceEl.animate(piece.frames, { duration: 650, fill: "forwards" });
      animation.onfinish = () => pieceEl.remove();
    });
  };

  const vibrateCut = () => {
    try {
      // Sem um toque anterior o Chrome bloqueia e reclama no console.
      const activation = navigator.userActivation;
      if (activation && !activation.hasBeenActive) {
        return;
      }
      if (typeof navigator.vibrate === "function") {
        navigator.vibrate(12);
      }
    } catch (error) {
      // Aparelho sem vibração: o corte segue normalmente.
    }
  };

  // Rastro da "lâmina" desenhado num canvas por cima da página.
  const trail = { canvas: null, ctx: null, points: [], frame: 0, width: 0, height: 0, ratio: 0 };

  const prepareTrailCanvas = () => {
    if (!trail.canvas || !trail.canvas.isConnected) {
      const canvas = document.createElement("canvas");
      const ctx = typeof canvas.getContext === "function" ? canvas.getContext("2d") : null;
      if (!ctx) {
        return null;
      }
      canvas.className = "slice-trail";
      canvas.setAttribute("aria-hidden", "true");
      document.body.appendChild(canvas);
      trail.canvas = canvas;
      trail.ctx = ctx;
      trail.width = 0;
    }
    const ratio = window.devicePixelRatio || 1;
    const width = window.innerWidth;
    const height = window.innerHeight;
    if (trail.width !== width || trail.height !== height || trail.ratio !== ratio) {
      trail.canvas.width = Math.round(width * ratio);
      trail.canvas.height = Math.round(height * ratio);
      trail.width = width;
      trail.height = height;
      trail.ratio = ratio;
      trail.ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    }
    return trail.ctx;
  };

  const drawTrail = () => {
    trail.frame = 0;
    const ctx = prepareTrailCanvas();
    if (!ctx) {
      trail.points = [];
      return;
    }
    const now = performance.now();
    trail.points = trail.points.filter((point) => now - point.time < TRAIL_LIFETIME_MS);
    ctx.clearRect(0, 0, trail.width, trail.height);

    const points = trail.points;
    if (points.length > 1) {
      ctx.lineCap = "round";
      ctx.shadowColor = "rgba(255, 255, 255, 0.85)";
      ctx.shadowBlur = 14;
      for (let i = 1; i < points.length; i += 1) {
        const from = points[i - 1];
        const to = points[i];
        const life = 1 - (now - to.time) / TRAIL_LIFETIME_MS;
        const tip = i / (points.length - 1);
        ctx.strokeStyle = `rgba(255, 255, 255, ${(0.35 + 0.6 * tip) * life})`;
        ctx.lineWidth = 1.5 + 6 * tip * life;
        ctx.beginPath();
        ctx.moveTo(from.x, from.y);
        ctx.lineTo(to.x, to.y);
        ctx.stroke();
      }
    }

    if (points.length) {
      trail.frame = requestAnimationFrame(drawTrail);
    }
  };

  const addTrailPoint = (x, y) => {
    trail.points.push({ x, y, time: performance.now() });
    if (trail.points.length > 48) {
      trail.points.splice(0, trail.points.length - 48);
    }
    if (!trail.frame) {
      trail.frame = requestAnimationFrame(drawTrail);
    }
  };

  // Aplica as regras da casa ao corte de um palito. Devolve true se cortou.
  const cutStick = (rowIndex, stickIndex, slice, { deferEmit = false } = {}) => {
    if (state.winner) return false;
    if (!state.rows[rowIndex]?.[stickIndex]) return false;
    if (waitingForOpponent()) {
      showRuleMessage(`Aguarde sua vez: agora é a vez de ${currentTurnName()}.`);
      return false;
    }
    if (state.activeRow !== null && state.activeRow !== rowIndex) {
      showRuleMessage("Conclua esta linha antes de cortar outra.");
      return false;
    }

    ensureBaseline();
    recalcTurnProgress();

    if (state.turnRemovalCount >= 3) {
      showRuleMessage("Você já removeu três palitos neste turno.");
      return false;
    }

    const rowRemovalCount = state.turnRowRemovalCounts[rowIndex] || 0;
    const originRow = Array.isArray(state.turnOriginRows[rowIndex])
      ? state.turnOriginRows[rowIndex]
      : [];
    const startedAsSplitRow =
      originRow.length === 3 &&
      Boolean(originRow[0]) &&
      Boolean(originRow[2]) &&
      !originRow[1];
    const shouldEnforceAlternateRule = startedAsSplitRow;
    if (shouldEnforceAlternateRule && rowRemovalCount >= 1) {
      showRuleMessage(
        "Nesta linha, apenas um palito pode ser cortado por turno após retirar o do meio."
      );
      return false;
    }

    if (state.activeRow === null) {
      state.activeRow = rowIndex;
      state.selectionRange = { row: rowIndex, min: stickIndex, max: stickIndex };
    } else if (state.selectionRange) {
      if (state.selectionRange.row !== rowIndex) {
        return false;
      }

      const isAdjacentToMin = stickIndex === state.selectionRange.min - 1;
      const isAdjacentToMax = stickIndex === state.selectionRange.max + 1;

      if (!isAdjacentToMin && !isAdjacentToMax) {
        return false;
      }

      state.selectionRange = {
        row: rowIndex,
        min: isAdjacentToMin ? stickIndex : state.selectionRange.min,
        max: isAdjacentToMax ? stickIndex : state.selectionRange.max,
      };
    }

    const updated = cloneRows(state.rows);
    if (!updated[rowIndex] || updated[rowIndex][stickIndex] === false) {
      return false;
    }

    updated[rowIndex][stickIndex] = false;
    state.rows = updated;
    if (!state.selectionRange) {
      state.selectionRange = { row: rowIndex, min: stickIndex, max: stickIndex };
    }

    state.ruleMessage = null;

    recalcTurnProgress();
    state.hasPlayed = state.turnRemovalCount > 0;

    const nextRow = updated[rowIndex] || [];
    const remaining = nextRow.filter(Boolean).length;
    const baselineRow = Array.isArray(state.turnOriginRows[rowIndex])
      ? state.turnOriginRows[rowIndex]
      : [];
    const baselineWasSplit = isSplitRow(baselineRow);
    const nextIsSplit = isSplitRow(nextRow);

    if (baselineWasSplit) {
      if (!nextIsSplit || remaining <= 1) {
        state.alternateRows[rowIndex] = false;
      }
    } else if (remaining <= 1) {
      state.alternateRows[rowIndex] = false;
    }

    playSliceEffect(slice);
    vibrateCut();
    if (!deferEmit) {
      emitState();
    }
    render();
    return true;
  };

  // Fração do segmento (x0,y0)→(x1,y1) em que ele entra no retângulo
  // (Liang–Barsky), ou null se não o atravessa.
  const segmentEntry = (x0, y0, x1, y1, box) => {
    const dx = x1 - x0;
    const dy = y1 - y0;
    let enter = 0;
    let leave = 1;
    const edges = [
      [-dx, x0 - box.left],
      [dx, box.right - x0],
      [-dy, y0 - box.top],
      [dy, box.bottom - y0],
    ];
    for (const [p, q] of edges) {
      if (p === 0) {
        if (q < 0) return null;
        continue;
      }
      const t = q / p;
      if (p < 0) {
        enter = Math.max(enter, t);
      } else {
        leave = Math.min(leave, t);
      }
      if (enter > leave) return null;
    }
    return enter;
  };

  // Corta, na ordem em que o dedo passou, os palitos cruzados pelo trecho.
  const sliceAlong = (x0, y0, x1, y1) => {
    const dx = x1 - x0;
    const dy = y1 - y0;
    const hits = [];
    container.querySelectorAll(".stick[data-row]:not(.stick--hidden)").forEach((stickEl) => {
      const rect = stickEl.getBoundingClientRect();
      const entry = segmentEntry(x0, y0, x1, y1, {
        left: rect.left - STICK_HIT_SLOP_PX,
        right: rect.right + STICK_HIT_SLOP_PX,
        top: rect.top - STICK_HIT_SLOP_PX,
        bottom: rect.bottom + STICK_HIT_SLOP_PX,
      });
      if (entry !== null) {
        hits.push({
          entry,
          rect,
          row: Number(stickEl.dataset.row),
          stick: Number(stickEl.dataset.stick),
        });
      }
    });

    hits.sort((a, b) => a.entry - b.entry);
    hits.forEach((hit) => {
      const centerX = hit.rect.left + hit.rect.width / 2;
      const along = Math.abs(dx) > 0.01 ? clamp((centerX - x0) / dx, 0, 1) : 0.5;
      const slice = { rect: hit.rect, x: x0 + along * dx, y: y0 + along * dy, dx, dy };
      if (cutStick(hit.row, hit.stick, slice, { deferEmit: true }) && swipe) {
        swipe.pendingEmit = true;
      }
    });
  };

  const endSwipe = () => {
    if (!swipe) {
      return;
    }
    const finished = swipe;
    swipe = null;
    if (finished.active) {
      suppressClickUntil = performance.now() + 400;
    }
    if (finished.pendingEmit) {
      emitState();
    }
  };

  const handleSwipePoint = (x, y) => {
    if (!swipe.active) {
      const dx = x - swipe.startX;
      const dy = y - swipe.startY;
      if (Math.hypot(dx, dy) < SWIPE_ACTIVATION_PX) {
        return;
      }
      // No toque, gesto vertical continua rolando a página (touch-action:
      // pan-y no tabuleiro): só o deslize de lado corta.
      if (swipe.pointerType !== "mouse" && Math.abs(dy) > Math.abs(dx)) {
        swipe = null;
        return;
      }
      swipe.active = true;
      addTrailPoint(swipe.startX, swipe.startY);
    }
    addTrailPoint(x, y);
    sliceAlong(swipe.lastX, swipe.lastY, x, y);
    if (swipe) {
      swipe.lastX = x;
      swipe.lastY = y;
    }
  };

  // Ouvintes no #root e na janela, que sobrevivem ao render().
  container.addEventListener("pointerdown", (event) => {
    if (swipe || !event.isPrimary) return;
    if (event.pointerType === "mouse" && event.button !== 0) return;
    const target = event.target;
    if (!(target instanceof Element) || !target.closest(".stick-board")) return;
    swipe = {
      pointerId: event.pointerId,
      pointerType: event.pointerType,
      startX: event.clientX,
      startY: event.clientY,
      lastX: event.clientX,
      lastY: event.clientY,
      active: false,
      pendingEmit: false,
    };
  });

  window.addEventListener("pointermove", (event) => {
    if (!swipe || event.pointerId !== swipe.pointerId) return;
    if (event.pointerType === "mouse" && event.buttons === 0) {
      // Botão solto fora da janela: o pointerup não chegou.
      endSwipe();
      return;
    }
    const coalesced =
      typeof event.getCoalescedEvents === "function" ? event.getCoalescedEvents() : [];
    const samples = coalesced.length ? coalesced : [event];
    for (const sample of samples) {
      if (!swipe) break;
      handleSwipePoint(sample.clientX, sample.clientY);
    }
  });

  const finishSwipeFor = (event) => {
    if (swipe && event.pointerId === swipe.pointerId) {
      endSwipe();
    }
  };
  window.addEventListener("pointerup", finishSwipeFor);
  window.addEventListener("pointercancel", finishSwipeFor);
  window.addEventListener("blur", endSwipe);

  const render = () => {
    document.body.style.background = state.bgGradient;
    document.body.style.backgroundAttachment = "fixed";
    // O link de volta mora no cabeçalho do jogo; devolve-o ao body antes de
    // limpar o #root para não perdê-lo (a tela de erro usa a posição fixa).
    if (backLink && backLink.parentNode !== document.body) {
      document.body.prepend(backLink);
    }
    container.innerHTML = "";

    if (state.mode === "online" && state.roomError) {
      const errorBox = document.createElement("div");
      errorBox.className = "game-error";

      const errorTitle = document.createElement("h2");
      errorTitle.className = "game-error__title";
      errorTitle.textContent = "Sala indisponível";
      errorBox.appendChild(errorTitle);

      const errorText = document.createElement("p");
      errorText.className = "game-error__text";
      errorText.textContent = state.roomError;
      errorBox.appendChild(errorText);

      container.appendChild(errorBox);
      return;
    }

    const wrapper = document.createElement("div");
    wrapper.className = "game-container";
    wrapper.style.setProperty("--stick-color", state.stickColor);

    const header = document.createElement("div");
    header.className = "game-header";
    if (backLink) {
      header.appendChild(backLink);
    }

    const title = document.createElement("h1");
    title.className = "game-title";
    const titleIcon = document.createElement("span");
    titleIcon.className = "game-title__icon";
    titleIcon.textContent = "🎮 ";
    title.append(titleIcon, "Desafio Secreto");
    header.appendChild(title);

    const modeSwitch = document.createElement("div");
    modeSwitch.className = "mode-switch";

    const modeLabel = document.createElement("span");
    modeLabel.className = "mode-switch__label";
    modeLabel.textContent = "Modo de jogo:";
    modeSwitch.appendChild(modeLabel);

    const modeOptions = document.createElement("div");
    modeOptions.className = "mode-switch__options";

    const onlineOption = document.createElement("button");
    onlineOption.type = "button";
    onlineOption.className = "mode-switch__option";
    if (state.mode === "online") {
      onlineOption.classList.add("mode-switch__option--active");
    }
    onlineOption.disabled = !supportsSocket;
    onlineOption.textContent = "Online";
    onlineOption.addEventListener("click", () => {
      setMode("online");
    });
    modeOptions.appendChild(onlineOption);

    const localOption = document.createElement("button");
    localOption.type = "button";
    localOption.className = "mode-switch__option";
    if (state.mode === "local") {
      localOption.classList.add("mode-switch__option--active");
    }
    localOption.textContent = "Local";
    localOption.addEventListener("click", () => {
      setMode("local");
    });
    modeOptions.appendChild(localOption);

    modeSwitch.appendChild(modeOptions);
    header.appendChild(modeSwitch);
    wrapper.appendChild(header);

    const shareBox = document.createElement("div");
    shareBox.className = "share-box";
    if (isOnlineMode()) {
      const shareLink = `${window.location.origin}${window.location.pathname}?sala=${roomCode}`;
      const shareLabel = document.createElement("span");
      shareLabel.className = "share-box__label";
      shareLabel.textContent = "Convide:";
      shareBox.appendChild(shareLabel);

      const shareCode = document.createElement("code");
      shareCode.textContent = shareLink;
      shareCode.title = shareLink;
      shareBox.appendChild(shareCode);

      const copyButton = document.createElement("button");
      copyButton.type = "button";
      copyButton.className = "share-box__copy";
      copyButton.textContent = "Copiar";
      copyButton.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(shareLink);
          copyButton.textContent = "Copiado!";
        } catch (error) {
          // Sem acesso à área de transferência: seleciona o link para copiar.
          const selection = window.getSelection();
          const range = document.createRange();
          range.selectNodeContents(shareCode);
          selection.removeAllRanges();
          selection.addRange(range);
          copyButton.textContent = "Selecionado";
        }
        setTimeout(() => {
          copyButton.textContent = "Copiar";
        }, 1600);
      });
      shareBox.appendChild(copyButton);

      if (state.connection !== "connected") {
        const connectionNotice = document.createElement("p");
        connectionNotice.className = "share-box__status";
        connectionNotice.textContent =
          state.connection === "offline"
            ? "Sem conexão com o servidor. Tentando reconectar… Enquanto isso, dá para jogar no modo local."
            : "Conectando ao servidor…";
        shareBox.appendChild(connectionNotice);
      }
    } else if (!supportsSocket) {
      shareBox.textContent =
        "Modo online indisponível. Continue jogando no modo local com seus amigos.";
    } else {
      shareBox.textContent = "Modo local: alternem a vez na mesma tela.";
    }
    wrapper.appendChild(shareBox);

    const status = document.createElement("p");
    status.className = "status-text";
    const currentNames = [
      sanitizeName(state.playerNames[0], DEFAULT_PLAYER_NAMES[0]),
      sanitizeName(state.playerNames[1], DEFAULT_PLAYER_NAMES[1]),
    ];

    state.playerNames = currentNames;

    // Nomes vêm do adversário no online: sempre como texto, nunca como HTML.
    const statusEmoji = document.createElement("span");
    statusEmoji.className = "emoji";
    if (state.winner) {
      const emoji = state.playerEmojis[state.winner - 1] || "🐾";
      const winnerName = currentNames[state.winner - 1] || `Jogador ${state.winner}`;
      statusEmoji.textContent = "🏆";
      status.append(statusEmoji, `${emoji} ${winnerName} venceu!`);
    } else {
      const emoji = state.playerEmojis[state.turn - 1] || "🐾";
      const activeName = currentNames[state.turn - 1] || `Jogador ${state.turn}`;
      statusEmoji.textContent = emoji;
      status.append(`Vez de ${activeName} `, statusEmoji);
    }
    wrapper.appendChild(status);

    if (
      state.lastTurn &&
      typeof state.lastTurn === "object" &&
      (state.lastTurn.message || (Array.isArray(state.lastTurn.removed) && state.lastTurn.removed.length))
    ) {
      const summaryBox = document.createElement("div");
      summaryBox.className = "turn-summary";

      if (state.lastTurn.message) {
        const summaryText = document.createElement("p");
        summaryText.className = "turn-summary__text";
        summaryText.textContent = state.lastTurn.message;
        summaryBox.appendChild(summaryText);
      } else if (Array.isArray(state.lastTurn.removed) && state.lastTurn.removed.length) {
        // A mensagem do servidor já descreve os palitos removidos; a lista só
        // aparece quando ela falta, para economizar altura.
        const detailList = document.createElement("ul");
        detailList.className = "turn-summary__list";

        state.lastTurn.removed.forEach((entry) => {
          const count = Number.parseInt(entry.count, 10);
          const rowLabel = Number.parseInt(entry.row, 10);
          if (!Number.isFinite(count) || count <= 0 || !Number.isFinite(rowLabel) || rowLabel <= 0) {
            return;
          }
          const listItem = document.createElement("li");
          const noun = count === 1 ? "palito" : "palitos";
          listItem.textContent = `${count} ${noun} na linha ${rowLabel}`;
          detailList.appendChild(listItem);
        });

        if (detailList.childElementCount) {
          summaryBox.appendChild(detailList);
        }
      }

      if (summaryBox.childElementCount) {
        wrapper.appendChild(summaryBox);
      }
    }

    const namesSection = document.createElement("div");
    namesSection.className = "names-section";

    currentNames.forEach((name, index) => {
      const field = document.createElement("div");
      field.className = "name-field";
      if (!state.winner && state.turn === index + 1) {
        field.classList.add("name-field--active");
      }

      const label = document.createElement("label");
      label.className = "name-label";
      const isMySeat = isOnlineMode() && state.mySeat === index + 1;
      label.textContent = isMySeat ? `Jogador ${index + 1} · você` : `Jogador ${index + 1}`;
      label.setAttribute("for", `player-name-${index}`);
      field.appendChild(label);

      const input = document.createElement("input");
      input.className = "name-input";
      input.type = "text";
      input.id = `player-name-${index}`;
      input.placeholder = `Nome do Jogador ${index + 1}`;
      input.value = name;
      input.maxLength = 40;

      const applyUpdate = () => {
        const updated = sanitizeName(input.value, DEFAULT_PLAYER_NAMES[index]);
        if (state.playerNames[index] === updated) {
          input.value = updated;
          return;
        }
        const nextNames = state.playerNames.slice();
        nextNames[index] = updated;
        state.playerNames = nextNames;
        input.value = updated;
        emitState();
        render();
      };

      input.addEventListener("blur", applyUpdate);
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          input.blur();
        }
      });

      field.appendChild(input);
      namesSection.appendChild(field);
    });

    wrapper.appendChild(namesSection);

    const board = document.createElement("div");
    board.className = "stick-board";

    state.rows.forEach((row, rowIndex) => {
      const rowEl = document.createElement("div");
      rowEl.className = "stick-row";
      if (state.activeRow !== null && state.activeRow !== rowIndex) {
        rowEl.classList.add("stick-row--disabled");
      }
      if (state.alternateRows[rowIndex]) {
        rowEl.classList.add("stick-row--locked");
        rowEl.setAttribute(
          "title",
          "Nesta linha, apenas um palito pode ser cortado por turno."
        );
      }

      row.forEach((stick, stickIndex) => {
        const stickEl = document.createElement("div");
        stickEl.className = "stick";
        if (!stick) {
          stickEl.classList.add("stick--hidden");
        }

        stickEl.dataset.row = String(rowIndex);
        stickEl.dataset.stick = String(stickIndex);

        stickEl.addEventListener("click", (event) => {
          // O clique que encerra um deslize não deve cortar de novo.
          if (performance.now() < suppressClickUntil) return;
          const rect = stickEl.getBoundingClientRect();
          const hasPoint = Boolean(event.clientX || event.clientY);
          cutStick(rowIndex, stickIndex, {
            rect,
            x: hasPoint ? event.clientX : rect.left + rect.width / 2,
            y: hasPoint ? event.clientY : rect.top + rect.height / 2,
            dx: 1,
            dy: 0,
          });
        });

        rowEl.appendChild(stickEl);
      });

      board.appendChild(rowEl);
    });

    wrapper.appendChild(board);

    // Abaixo do tabuleiro: acima dele o aviso empurrava os palitos no meio de
    // um deslize e, no celular, ficava fora da tela de quem está jogando.
    if (typeof state.ruleMessage === "string" && state.ruleMessage.trim()) {
      const ruleNotice = document.createElement("p");
      ruleNotice.className = "rule-message";
      ruleNotice.textContent = state.ruleMessage;
      wrapper.appendChild(ruleNotice);
    } else if (!state.winner) {
      const hint = document.createElement("p");
      hint.className = "board-hint";
      hint.textContent = "✂️ Deslize sobre os palitos para cortar (ou toque).";
      wrapper.appendChild(hint);
    }

    const controls = document.createElement("div");
    controls.className = "controls";

    const endTurnButton = document.createElement("button");
    endTurnButton.type = "button";
    endTurnButton.className = "button button--primary";
    endTurnButton.textContent = "Finalizar Turno";
    endTurnButton.disabled = !state.hasPlayed || Boolean(state.winner);
    endTurnButton.addEventListener("click", () => {
      if (!state.hasPlayed || state.winner) {
        return;
      }

      const nextRows = cloneRows(state.rows);
      const nextTurn = state.turn === 1 ? 2 : 1;
      const allTaken = nextRows.every((row) => row.every((stick) => !stick));
      const winningPlayer = allTaken ? nextTurn : null;

      state.turn = nextTurn;
      state.winner = winningPlayer;
      state.hasPlayed = false;
      state.activeRow = null;
      state.selectionRange = null;
      state.turnOriginRows = cloneRows(state.rows);
      state.alternateRows = computeAlternateRows(state.rows);
      state.turnRemovalCount = 0;
      state.turnRowRemovalCounts = createZeroArray(state.rows.length);
      state.ruleMessage = null;
      resetArmedUntil = 0;

      emitState();
      render();
    });

    const isGameInProgress = () =>
      !state.winner && state.rows.some((row) => row.some((stick) => !stick));
    const resetArmed = isGameInProgress() && performance.now() < resetArmedUntil;

    const resetButton = document.createElement("button");
    resetButton.type = "button";
    resetButton.className = "button button--reset";
    if (resetArmed) {
      resetButton.classList.add("button--armed");
    }
    resetButton.textContent = resetArmed ? RESET_CONFIRM_LABEL : RESET_LABEL;
    resetButton.addEventListener("click", () => {
      if (waitingForOpponent()) {
        state.ruleMessage = `Na partida online, só quem está na vez (${currentTurnName()}) pode reiniciar.`;
        render();
        return;
      }
      // Com a partida em andamento, o primeiro toque só pede confirmação: um
      // toque errado perto de "Finalizar Turno" não apaga mais o jogo.
      if (isGameInProgress() && performance.now() >= resetArmedUntil) {
        resetArmedUntil = performance.now() + RESET_CONFIRM_MS;
        resetButton.classList.add("button--armed");
        resetButton.textContent = RESET_CONFIRM_LABEL;
        clearTimeout(resetDisarmTimer);
        resetDisarmTimer = setTimeout(() => {
          resetArmedUntil = 0;
          // Sem render(): não apaga o nome de quem estiver digitando.
          const current = container.querySelector(".button--reset");
          if (current) {
            current.classList.remove("button--armed");
            current.textContent = RESET_LABEL;
          }
        }, RESET_CONFIRM_MS);
        return;
      }
      resetArmedUntil = 0;
      clearTimeout(resetDisarmTimer);
      const currentNames = [
        sanitizeName(state.playerNames[0], DEFAULT_PLAYER_NAMES[0]),
        sanitizeName(state.playerNames[1], DEFAULT_PLAYER_NAMES[1]),
      ];
      state.playerNames = [currentNames[1], currentNames[0]];

      if (Array.isArray(state.playerEmojis) && state.playerEmojis.length >= 2) {
        state.playerEmojis = [state.playerEmojis[1], state.playerEmojis[0]];
      }

      state.rows = cloneRows(INITIAL_ROWS);
      state.startingPlayer = state.startingPlayer === 1 ? 2 : 1;
      state.turn = state.startingPlayer;
      state.winner = null;
      state.hasPlayed = false;
      state.activeRow = null;
      state.selectionRange = null;
      state.bgGradient = randomGradient();
      state.stickColor = randomColor();
      if (!Array.isArray(state.playerEmojis) || state.playerEmojis.length < 2) {
        state.playerEmojis = [randomEmoji(), randomEmoji()];
      }
      state.turnOriginRows = cloneRows(INITIAL_ROWS);
      state.turnRemovalCount = 0;
      state.turnRowRemovalCounts = createZeroArray(INITIAL_ROWS.length);
      state.alternateRows = INITIAL_ROWS.map(() => false);
      state.ruleMessage = null;
      state.lastTurn = null;

      emitState();
      render();
    });

    // Reiniciar à esquerda, pequeno e discreto; Finalizar Turno à direita.
    controls.append(resetButton, endTurnButton);

    wrapper.appendChild(controls);
    container.appendChild(wrapper);
  };

  if (supportsSocket) {
    socket.on("update_state", (data) => {
      if (!isOnlineMode()) {
        return;
      }
      if (!data) {
        return;
      }
      // Cortes deste deslize ainda não enviados: aplicar agora devolveria os
      // palitos ao tabuleiro. O envio no fim do gesto traz o estado completo.
      if (swipe && swipe.pendingEmit) {
        return;
      }

      state.roomError = null;

      const previousTurn = state.turn;
      const incomingRows = normalizeRows(data.rows, state.rows);
      state.rows = incomingRows;

      const turnValue = Number.parseInt(data.turn, 10);
      if (turnValue === 1 || turnValue === 2) {
        state.turn = turnValue;
      }

      const winnerValue = Number.parseInt(data.winner, 10);
      state.winner = winnerValue === 1 || winnerValue === 2 ? winnerValue : null;

      const startingValue = Number.parseInt(
        data.starting_player ?? data.startingPlayer,
        10,
      );
      if (startingValue === 1 || startingValue === 2) {
        state.startingPlayer = startingValue;
      }

      const playersValue = data.players;
      if (playersValue && typeof playersValue === "object") {
        const updatedNames = [];
        for (let i = 0; i < 2; i += 1) {
          const key = i + 1;
          const raw =
            playersValue[key] ??
            playersValue[String(key)] ??
            playersValue[i] ??
            playersValue[String(i)];
          updatedNames[i] = sanitizeName(
            raw,
            DEFAULT_PLAYER_NAMES[i]
          );
        }
        state.playerNames = updatedNames;
      }

      const normalizeBoolean = (value, fallback) => {
        if (typeof value === "boolean") {
          return value;
        }
        if (typeof value === "number") {
          return value !== 0;
        }
        if (typeof value === "string") {
          const normalized = value.trim().toLowerCase();
          if (["1", "true", "yes", "on"].includes(normalized)) {
            return true;
          }
          if (["0", "false", "no", "off", ""].includes(normalized)) {
            return false;
          }
        }
        return Boolean(fallback);
      };

      state.hasPlayed = normalizeBoolean(
        data.has_played ?? data.hasPlayed,
        state.hasPlayed
      );

      const originSource = data.turn_origin_rows ?? data.turnOriginRows;
      if (Array.isArray(originSource)) {
        state.turnOriginRows = normalizeRows(
          originSource,
          state.turnOriginRows || state.rows
        );
      }

      if (
        !Array.isArray(state.turnOriginRows) ||
        state.turnOriginRows.length !== state.rows.length ||
        !state.hasPlayed ||
        previousTurn !== state.turn
      ) {
        state.turnOriginRows = cloneRows(state.rows);
      }

      const alternateSource = data.alternate_rows ?? data.alternateRows;
      if (Array.isArray(alternateSource)) {
        state.alternateRows = state.rows.map((_, index) =>
          Boolean(alternateSource[index])
        );
      } else if (
        !Array.isArray(state.alternateRows) ||
        state.alternateRows.length !== state.rows.length
      ) {
        state.alternateRows = state.rows.map(() => false);
      }

      const incomingActiveRow = data.active_row ?? data.activeRow;
      const parsedActiveRow = Number.parseInt(incomingActiveRow, 10);
      if (
        Number.isInteger(parsedActiveRow) &&
        parsedActiveRow >= 0 &&
        parsedActiveRow < state.rows.length
      ) {
        state.activeRow = parsedActiveRow;
      } else {
        state.activeRow = null;
      }

      state.selectionRange = null;

      recalcTurnProgress();
      state.ruleMessage = null;

      let shouldEmitTheme = false;

      const incomingGradient =
        typeof data.bg_gradient === "string" ? data.bg_gradient.trim() : "";
      if (incomingGradient) {
        state.bgGradient = incomingGradient.slice(0, 200);
      } else if (data.bg_gradient === null || typeof data.bg_gradient === "undefined") {
        shouldEmitTheme = true;
      }

      const incomingStickColor =
        typeof data.stick_color === "string" ? data.stick_color.trim() : "";
      if (incomingStickColor) {
        state.stickColor = incomingStickColor.slice(0, 50);
      } else if (data.stick_color === null || typeof data.stick_color === "undefined") {
        shouldEmitTheme = true;
      }

      if (Array.isArray(data.player_emojis) && data.player_emojis.length) {
        const sanitized = [];
        for (let i = 0; i < 2; i += 1) {
          const raw = data.player_emojis[i];
          const text = typeof raw === "string" ? raw.trim() : `${raw || ""}`;
          sanitized.push(text.slice(0, 8) || "🐾");
        }
        state.playerEmojis = sanitized;
      } else if (
        data.player_emojis === null ||
        typeof data.player_emojis === "undefined"
      ) {
        shouldEmitTheme = true;
      }

      if (shouldEmitTheme) {
        emitState();
      }

      if (Object.prototype.hasOwnProperty.call(data, "last_turn")) {
        if (data.last_turn === null) {
          state.lastTurn = null;
        } else if (data.last_turn && typeof data.last_turn === "object") {
          const summary = data.last_turn;
          const sanitizedRemoved = Array.isArray(summary.removed)
            ? summary.removed
                .slice(0, 5)
                .map((entry) => {
                  const rowValue = Number.parseInt(entry.row, 10);
                  const countValue = Number.parseInt(entry.count, 10);
                  if (!Number.isFinite(rowValue) || rowValue <= 0) {
                    return null;
                  }
                  if (!Number.isFinite(countValue) || countValue <= 0) {
                    return null;
                  }
                  return { row: rowValue, count: countValue };
                })
                .filter(Boolean)
            : [];

          const messageText =
            typeof summary.message === "string"
              ? summary.message.trim().slice(0, 200)
              : "";

          if (messageText || sanitizedRemoved.length) {
            state.lastTurn = {
              message: messageText,
              removed: sanitizedRemoved,
            };
          } else {
            state.lastTurn = null;
          }
        }
      }

      render();
    });

    socket.on("seat", (payload) => {
      const seatValue = Number.parseInt(payload && payload.seat, 10);
      state.mySeat = seatValue === 1 || seatValue === 2 ? seatValue : null;
      if (isOnlineMode()) {
        render();
      }
    });

    socket.on("room_full", (payload) => {
      if (state.mode !== "online") {
        return;
      }

      const message =
        payload && typeof payload.message === "string"
          ? payload.message.trim()
          : "";
      state.roomError =
        message || "Sala cheia. Tente outra sala ou gere um novo código.";
      render();
    });

    // Só redesenha quando o estado muda: o cliente tenta reconectar a cada
    // poucos segundos e um render por tentativa apagaria o nome em digitação.
    const setConnection = (next) => {
      if (state.connection === next) {
        return false;
      }
      state.connection = next;
      return state.mode === "online";
    };

    socket.on("connect_error", () => {
      if (setConnection("offline")) {
        render();
      }
    });

    socket.on("disconnect", (reason) => {
      const changed = setConnection("offline");
      if (state.mode !== "online") {
        return;
      }

      if (!state.roomError && reason === "io server disconnect") {
        state.roomError = "Conexão encerrada pelo servidor.";
        render();
        return;
      }
      if (changed) {
        render();
      }
    });

    socket.on("connect", () => {
      const changed = setConnection("connected");
      if (state.mode === "online") {
        state.roomError = null;
        if (changed) {
          render();
        }
      }
    });
  }

  render();
})();

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
  if (!socket) {
    return;
  }

  const INITIAL_ROWS = [
    [true, true, true],
    [true, true, true],
    [true, true, true],
    [true, true],
    [true, true],
  ];

  const cloneRows = (rows) => rows.map((row) => row.slice());

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
    winner: null,
    hasPlayed: false,
    activeRow: null,
    bgGradient: randomGradient(),
    stickColor: randomColor(),
    playerEmojis: [randomEmoji(), randomEmoji()],
    playerNames: DEFAULT_PLAYER_NAMES.slice(),
  };

  const container = document.getElementById("root");
  if (!container) {
    return;
  }

  document.body.classList.add("game-body");

  const normalizeRows = (rows) =>
    Array.isArray(rows)
      ? rows.map((row) =>
          Array.isArray(row) ? row.map((stick) => Boolean(stick)) : []
        )
      : cloneRows(INITIAL_ROWS);

  const emitState = () => {
    socket.emit("move", {
      rows: cloneRows(state.rows).map((row) => row.map(Boolean)),
      turn: state.turn,
      winner: state.winner,
      players: {
        1: sanitizeName(state.playerNames[0], DEFAULT_PLAYER_NAMES[0]),
        2: sanitizeName(state.playerNames[1], DEFAULT_PLAYER_NAMES[1]),
      },
    });
  };

  const render = () => {
    document.body.style.background = state.bgGradient;
    document.body.style.backgroundAttachment = "fixed";
    container.innerHTML = "";

    const wrapper = document.createElement("div");
    wrapper.className = "game-container";
    wrapper.style.setProperty("--stick-color", state.stickColor);

    const title = document.createElement("h1");
    title.className = "game-title";
    title.textContent = "🎮 Desafio Secreto";
    wrapper.appendChild(title);

    const shareBox = document.createElement("div");
    shareBox.className = "share-box";
    const shareLink = `${window.location.origin}${window.location.pathname}?sala=${roomCode}`;
    shareBox.innerHTML = `Convide alguém com este link:<br><code>${shareLink}</code>`;
    wrapper.appendChild(shareBox);

    const status = document.createElement("p");
    status.className = "status-text";
    const currentNames = [
      sanitizeName(state.playerNames[0], DEFAULT_PLAYER_NAMES[0]),
      sanitizeName(state.playerNames[1], DEFAULT_PLAYER_NAMES[1]),
    ];

    state.playerNames = currentNames;

    if (state.winner) {
      const emoji = state.playerEmojis[state.winner - 1] || "🐾";
      const winnerName = currentNames[state.winner - 1] || `Jogador ${state.winner}`;
      status.innerHTML = `<span class="emoji">🏆</span>${emoji} ${winnerName} venceu!`;
    } else {
      const emoji = state.playerEmojis[state.turn - 1] || "🐾";
      const activeName = currentNames[state.turn - 1] || `Jogador ${state.turn}`;
      status.innerHTML = `Vez de ${activeName} <span class="emoji">${emoji}</span>`;
    }
    wrapper.appendChild(status);

    const namesSection = document.createElement("div");
    namesSection.className = "names-section";

    currentNames.forEach((name, index) => {
      const field = document.createElement("div");
      field.className = "name-field";

      const label = document.createElement("label");
      label.className = "name-label";
      label.textContent = `Jogador ${index + 1}`;
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

      row.forEach((stick, stickIndex) => {
        const stickEl = document.createElement("div");
        stickEl.className = "stick";
        if (!stick) {
          stickEl.classList.add("stick--hidden");
        }

        stickEl.addEventListener("click", () => {
          if (state.winner) return;
          if (!state.rows[rowIndex]?.[stickIndex]) return;
          if (state.activeRow !== null && state.activeRow !== rowIndex) return;

          const updated = cloneRows(state.rows);
          updated[rowIndex][stickIndex] = false;
          state.rows = updated;
          state.hasPlayed = true;
          if (state.activeRow === null) {
            state.activeRow = rowIndex;
          }
          render();
        });

        rowEl.appendChild(stickEl);
      });

      board.appendChild(rowEl);
    });

    wrapper.appendChild(board);

    const controls = document.createElement("div");
    controls.className = "controls";

    const endTurnButton = document.createElement("button");
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
      const winningPlayer = allTaken ? state.turn : null;

      state.turn = nextTurn;
      state.winner = winningPlayer;
      state.hasPlayed = false;
      state.activeRow = null;

      emitState();
      render();
    });
    controls.appendChild(endTurnButton);

    const resetButton = document.createElement("button");
    resetButton.className = "button button--secondary";
    resetButton.textContent = "Reiniciar";
    resetButton.addEventListener("click", () => {
      state.rows = cloneRows(INITIAL_ROWS);
      state.turn = 1;
      state.winner = null;
      state.hasPlayed = false;
      state.activeRow = null;
      state.bgGradient = randomGradient();
      state.stickColor = randomColor();
      state.playerEmojis = [randomEmoji(), randomEmoji()];

      emitState();
      render();
    });
    controls.appendChild(resetButton);

    wrapper.appendChild(controls);
    container.appendChild(wrapper);
  };

  socket.on("update_state", (data) => {
    if (!data) {
      return;
    }

    const incomingRows = normalizeRows(data.rows);
    if (incomingRows.length) {
      state.rows = incomingRows;
    }

    const turnValue = Number.parseInt(data.turn, 10);
    if (turnValue === 1 || turnValue === 2) {
      state.turn = turnValue;
    }

    const winnerValue = Number.parseInt(data.winner, 10);
    state.winner = winnerValue === 1 || winnerValue === 2 ? winnerValue : null;

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

    state.hasPlayed = false;
    state.activeRow = null;

    render();
  });

  render();
})();

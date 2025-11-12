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

  const state = {
    rows: cloneRows(INITIAL_ROWS),
    turn: 1,
    winner: null,
    hasPlayed: false,
    activeRow: null,
    bgGradient: randomGradient(),
    stickColor: randomColor(),
    playerEmojis: [randomEmoji(), randomEmoji()],
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

  const emitState = (rows, turn, winner) => {
    socket.emit("move", {
      rows: cloneRows(rows).map((row) => row.map(Boolean)),
      turn,
      winner,
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
    if (state.winner) {
      const emoji = state.playerEmojis[state.winner - 1] || "🐾";
      status.innerHTML = `<span class="emoji">🏆</span>${emoji} Jogador ${state.winner} venceu!`;
    } else {
      const emoji = state.playerEmojis[state.turn - 1] || "🐾";
      status.innerHTML = `Vez do Jogador ${state.turn} <span class="emoji">${emoji}</span>`;
    }
    wrapper.appendChild(status);

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

      emitState(nextRows, nextTurn, winningPlayer);
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

      emitState(state.rows, 1, null);
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

    state.hasPlayed = false;
    state.activeRow = null;

    render();
  });

  render();
})();

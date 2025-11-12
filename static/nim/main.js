(() => {
  const { useState, useEffect } = React;
  const { createRoot } = ReactDOM;
  const { motion } = window["framer-motion"];
  const socket = io();

  const INITIAL_ROWS = [
    [true, true, true],
    [true, true, true],
    [true, true, true],
    [true, true],
    [true, true]
  ];

  const cloneRows = (rows) => rows.map((row) => row.slice());

  const randomColor = () => `hsl(${Math.floor(Math.random() * 360)}, 70%, 70%)`;
  const randomGradient = () => {
    const c1 = randomColor();
    const c2 = randomColor();
    return `radial-gradient(circle at top left, ${c1}, ${c2})`;
  };

  const randomEmoji = () => {
    const emojis = ["😺", "🐶", "🐹", "🦊", "🐸", "🐼", "🐵", "🐰", "🐯", "🐮"];
    return emojis[Math.floor(Math.random() * emojis.length)];
  };

  function NimGame() {
    const [rows, setRows] = useState(cloneRows(INITIAL_ROWS));
    const [turn, setTurn] = useState(1);
    const [winner, setWinner] = useState(null);
    const [hasPlayed, setHasPlayed] = useState(false);
    const [activeRow, setActiveRow] = useState(null);
    const [bgGradient, setBgGradient] = useState(randomGradient);
    const [stickColor, setStickColor] = useState(randomColor);
    const [playerEmojis, setPlayerEmojis] = useState([randomEmoji(), randomEmoji()]);

    useEffect(() => {
      const handleUpdate = (data) => {
        if (!data || !Array.isArray(data.rows)) {
          return;
        }
        setRows(cloneRows(data.rows));
        if (typeof data.turn === "number") {
          setTurn(data.turn);
        }
        setWinner(Number.isInteger(data.winner) ? data.winner : null);
        setHasPlayed(false);
        setActiveRow(null);
      };

      socket.on("update_state", handleUpdate);
      return () => {
        socket.off("update_state", handleUpdate);
      };
    }, []);

    const handleClick = (rowIndex, stickIndex) => {
      if (winner) return;
      if (!rows[rowIndex]?.[stickIndex]) return;
      if (activeRow !== null && activeRow !== rowIndex) return;

      setRows((prevRows) => {
        const updated = prevRows.map((row) => row.slice());
        updated[rowIndex][stickIndex] = false;
        return updated;
      });
      setHasPlayed(true);
      if (activeRow === null) {
        setActiveRow(rowIndex);
      }
    };

    const emitState = (nextRows, nextTurn, nextWinner) => {
      const payload = {
        rows: cloneRows(nextRows),
        turn: nextTurn,
        winner: nextWinner,
      };
      socket.emit("move", payload);
    };

    const endTurn = () => {
      if (!hasPlayed || winner) return;
      const nextRows = cloneRows(rows);
      const nextTurn = turn === 1 ? 2 : 1;
      const allTaken = nextRows.every((row) => row.every((stick) => !stick));
      const winningPlayer = allTaken ? turn : null;

      setTurn(nextTurn);
      setWinner(winningPlayer);
      setHasPlayed(false);
      setActiveRow(null);

      emitState(nextRows, nextTurn, winningPlayer);
    };

    const resetGame = () => {
      const freshRows = cloneRows(INITIAL_ROWS);
      setRows(freshRows);
      setTurn(1);
      setWinner(null);
      setHasPlayed(false);
      setActiveRow(null);
      setBgGradient(randomGradient());
      setStickColor(randomColor());
      setPlayerEmojis([randomEmoji(), randomEmoji()]);
      emitState(freshRows, 1, null);
    };

    return (
      React.createElement(
        "div",
        {
          className: "flex flex-col items-center p-6 min-h-screen transition-all duration-700",
          style: { background: bgGradient },
        },
        React.createElement(
          "h1",
          { className: "text-3xl font-bold mb-4 text-white drop-shadow" },
          "🎮 Jogo de Nim"
        ),
        winner
          ? React.createElement(
              "div",
              { className: "text-xl font-semibold mb-4" },
              "🏆 ",
              playerEmojis[winner - 1] || "🐾",
              " Jogador ",
              winner,
              " venceu!"
            )
          : React.createElement(
              "div",
              { className: "text-lg mb-4" },
              "Vez do Jogador ",
              turn,
              " ",
              playerEmojis[turn - 1]
            ),
        React.createElement(
          "div",
          { className: "flex flex-col gap-3" },
          rows.map((row, rowIndex) =>
            React.createElement(
              "div",
              {
                key: `row-${rowIndex}`,
                className: `flex justify-center gap-3 ${
                  activeRow !== null && activeRow !== rowIndex ? "opacity-50" : ""
                }`,
              },
              row.map((stick, stickIndex) =>
                React.createElement(
                  motion.div,
                  {
                    key: `stick-${rowIndex}-${stickIndex}`,
                    whileHover: { scale: stick ? 1.1 : 1 },
                    whileTap: { scale: 0.9 },
                    className: `w-4 h-16 rounded-full cursor-pointer shadow-md transition-all duration-300 ${
                      stick ? "" : "bg-gray-300 opacity-50"
                    }`,
                    style: { backgroundColor: stick ? stickColor : undefined },
                    onClick: () => handleClick(rowIndex, stickIndex),
                  }
                )
              )
            )
          )
        ),
        !winner &&
          React.createElement(
            "button",
            {
              onClick: endTurn,
              disabled: !hasPlayed,
              className: `mt-6 px-4 py-2 rounded-xl text-white transition-all ${
                hasPlayed ? "bg-green-500 hover:bg-green-600" : "bg-gray-400 cursor-not-allowed"
              }`,
            },
            "Finalizar Turno"
          ),
        React.createElement(
          "button",
          {
            onClick: resetGame,
            className: "mt-3 bg-blue-500 text-white px-4 py-2 rounded-xl hover:bg-blue-600",
          },
          "Reiniciar"
        )
      )
    );
  }

  const container = document.getElementById("root");
  if (container) {
    const root = createRoot(container);
    root.render(React.createElement(NimGame));
  }
})();

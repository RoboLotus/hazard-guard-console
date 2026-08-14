import { useEffect, useRef, useState } from "react";
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Keyboard,
  StopCircle,
} from "@phosphor-icons/react";
import {
  isEditableKeyboardTarget,
  teleopDirectionForKey,
} from "../teleop.js";

const HEARTBEAT_MS = 100;

function socketUrl() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/teleop`;
}

export default function SimulationTeleop({ systemMode }) {
  const [connection, setConnection] = useState("waiting");
  const [activeDirection, setActiveDirection] = useState("stop");
  const [message, setMessage] = useState("Gazebo와 ROS 브리지를 기다리고 있습니다.");
  const socketRef = useRef(null);
  const heartbeatRef = useRef(null);
  const activeDirectionRef = useRef("stop");
  const pressedKeyRef = useRef(null);

  const driveSelected = ["mapping", "patrol"].includes(systemMode?.mode);
  const simulatorReady = Boolean(
    driveSelected
    && systemMode?.state === "running"
    && systemMode?.managed
    && systemMode?.simulation_state === "running"
    && systemMode?.simulation_managed
  );

  const send = (direction) => {
    const socket = socketRef.current;
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ direction }));
      return true;
    }
    return false;
  };

  const clearHeartbeat = () => {
    if (heartbeatRef.current !== null) {
      window.clearInterval(heartbeatRef.current);
      heartbeatRef.current = null;
    }
  };

  const stop = (force = false) => {
    clearHeartbeat();
    if (force || activeDirectionRef.current !== "stop") send("stop");
    activeDirectionRef.current = "stop";
    pressedKeyRef.current = null;
    setActiveDirection("stop");
  };

  const start = (direction) => {
    if (connection !== "connected" || direction === "stop") {
      stop(true);
      return;
    }
    clearHeartbeat();
    activeDirectionRef.current = direction;
    setActiveDirection(direction);
    send(direction);
    heartbeatRef.current = window.setInterval(() => send(direction), HEARTBEAT_MS);
  };

  useEffect(() => {
    if (!driveSelected || !simulatorReady) {
      setConnection("waiting");
      setMessage(
        driveSelected
          ? "시뮬레이션 환경이 실행되면 조작할 수 있습니다."
          : "맵 생성 또는 순찰 모드에서만 사용할 수 있습니다.",
      );
      return undefined;
    }

    setConnection("connecting");
    setMessage("시뮬레이션 조작 채널에 연결하는 중입니다.");
    const socket = new WebSocket(socketUrl());
    socketRef.current = socket;
    socket.onopen = () => setConnection("connecting");
    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.accepted) {
          setConnection("connected");
          setMessage(payload.message || "방향키 또는 WASD를 누르고 있는 동안 이동합니다.");
          if (payload.direction === "stop" && activeDirectionRef.current !== "stop") {
            clearHeartbeat();
            activeDirectionRef.current = "stop";
            setActiveDirection("stop");
          }
        } else {
          setConnection("error");
          setMessage(payload.message || "시뮬레이션 조작을 사용할 수 없습니다.");
          stop();
        }
      } catch {
        setConnection("error");
        setMessage("조작 채널 응답을 해석하지 못했습니다.");
      }
    };
    socket.onerror = () => {
      setConnection("error");
      setMessage("시뮬레이션 조작 채널에 연결하지 못했습니다.");
    };
    socket.onclose = () => {
      clearHeartbeat();
      activeDirectionRef.current = "stop";
      setActiveDirection("stop");
      setConnection((current) => (current === "error" ? current : "waiting"));
    };

    return () => {
      clearHeartbeat();
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ direction: "stop" }));
      }
      socket.close();
      if (socketRef.current === socket) socketRef.current = null;
      activeDirectionRef.current = "stop";
    };
  }, [driveSelected, simulatorReady]);

  useEffect(() => {
    if (!driveSelected) return undefined;
    const onKeyDown = (event) => {
      const direction = teleopDirectionForKey(event.code);
      if (!direction || isEditableKeyboardTarget(event.target)) return;
      event.preventDefault();
      if (event.repeat || pressedKeyRef.current === event.code) return;
      pressedKeyRef.current = event.code;
      start(direction);
    };
    const onKeyUp = (event) => {
      if (event.code !== pressedKeyRef.current) return;
      event.preventDefault();
      stop(true);
    };
    const onBlur = () => stop(true);
    const onVisibilityChange = () => {
      if (document.hidden) stop(true);
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    window.addEventListener("blur", onBlur);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("blur", onBlur);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  });

  if (!driveSelected) return null;

  const disabled = connection !== "connected";
  const button = (direction, label, Icon) => (
    <button
      type="button"
      className={`teleop-button ${direction} ${activeDirection === direction ? "active" : ""}`}
      aria-label={label}
      aria-pressed={activeDirection === direction}
      disabled={disabled}
      onContextMenu={(event) => event.preventDefault()}
      onPointerDown={(event) => {
        event.preventDefault();
        event.currentTarget.setPointerCapture?.(event.pointerId);
        start(direction);
      }}
      onPointerUp={() => stop(true)}
      onPointerCancel={() => stop(true)}
      onLostPointerCapture={() => stop(true)}
    >
      <Icon size={19} weight="bold" />
      <span>{label}</span>
    </button>
  );

  return (
    <section className="simulation-teleop" aria-label="시뮬레이션 가상 조작기">
      <header>
        <span className="teleop-title"><Keyboard size={16} weight="fill" />가상 조작기</span>
        <strong className={`teleop-connection ${connection}`}>SIMULATION ONLY</strong>
      </header>
      <p>{message}</p>
      <div className="teleop-controls">
        {button("forward", "전진", ArrowUp)}
        {button("left", "좌회전", ArrowLeft)}
        <button
          type="button"
          className="teleop-button stop"
          aria-label="즉시 정지"
          disabled={disabled}
          onClick={() => stop(true)}
        >
          <StopCircle size={20} weight="fill" />
          <span>정지</span>
        </button>
        {button("right", "우회전", ArrowRight)}
        {button("backward", "후진", ArrowDown)}
      </div>
      <small>
        버튼 또는 방향키/WASD를 누르고 있는 동안만 이동 · Space 정지
        {systemMode?.mode === "patrol" && " · 조작을 시작하면 진행 중인 순찰이 취소됩니다"}
      </small>
    </section>
  );
}

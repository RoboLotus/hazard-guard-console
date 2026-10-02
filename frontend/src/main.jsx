import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App.jsx";
import { loadRecording } from "./demo/data.js";
import { installRecordedDemo } from "./demo/runtime.js";
import "pretendard/dist/web/variable/pretendardvariable.css";
import "./styles.css";
import "./demo/banner.css";

const root = createRoot(document.getElementById("root"));
loadRecording().then(recording => {
  installRecordedDemo(recording);
  root.render(<React.StrictMode><App /></React.StrictMode>);
}).catch(error => {
  root.render(<div className="app-boot-loader"><div className="app-boot-loader__content" role="alert">
    <strong>시연 자료를 준비해주세요</strong><p>{error.message}</p>
    <button className="button secondary" onClick={() => location.reload()}>다시 불러오기</button>
  </div></div>);
});

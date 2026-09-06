import { useEffect, useState } from "react";
import { Camera, ThermometerHot } from "@phosphor-icons/react";
import { cameraStreamState } from "../cameraStream.js";
import { LiveImage, ConnectionPlaceholder } from "./Common.jsx";

export function useCameraFeed(stream) {
  const state = cameraStreamState(stream);
  const key = `${state.source}:${state.available}`;
  const [image, setImage] = useState({ key: null, loaded: false, failed: false });
  useEffect(() => setImage({ key, loaded: false, failed: false }), [key]);
  const live = state.available && image.key === key && image.loaded;
  const failed = image.key === key && image.failed;
  return {
    ...state, live,
    label: !state.available ? "연결 필요" : failed ? "영상 수신 실패" : !live ? "영상 수신 중" : state.simulated ? "SIMULATED" : "LIVE",
    onLoadState: (loaded) => setImage({ key, loaded, failed: !loaded }),
  };
}

export function CameraFeedLabel({ feed }) {
  return <span className={`live-label ${feed.live ? "" : "offline"}`}><span />{feed.label}</span>;
}

export function CameraFeedImage({ feed, thermal = false }) {
  const name = thermal ? "열화상" : "RGB";
  return <>
    {feed.available && <LiveImage
      key={feed.source}
      endpoint={`/api/v1/media/${thermal ? "thermal" : "rgb"}`}
      enabled interval={thermal ? 400 : 300}
      alt={`${name} 카메라 영상`}
      onLoadState={feed.onLoadState}
      style={{ visibility: feed.live ? "visible" : "hidden" }}
    />}
    {!feed.live && <div className="camera-feed-placeholder">
      <ConnectionPlaceholder icon={thermal ? ThermometerHot : Camera}
        title={feed.available ? feed.label : `${name} 카메라 연결이 필요합니다`}
        description={feed.available ? "영상 수신을 자동으로 다시 시도합니다." : "센서와 서버가 연결되면 영상이 표시됩니다."} />
    </div>}
  </>;
}

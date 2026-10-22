import { Link } from "react-router-dom";

import markUrl from "../assets/greenlit-mark.png";

/** Mark plus wordmark rendered as live text, readable on both themes. */
export function Brand() {
  return (
    <Link to="/" className="brand" aria-label="GreenLit home">
      <span className="brand__chip">
        <img className="brand__mark" src={markUrl} alt="" />
      </span>
      <span>
        <span className="brand__green">Green</span>
        <span className="brand__lit">Lit</span>
      </span>
    </Link>
  );
}

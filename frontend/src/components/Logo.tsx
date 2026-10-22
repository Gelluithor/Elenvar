import { useId } from "react";

// Geometrie loga „Bdělé oko“ (viewBox 128 × 128). Barvy určuje CSS podle motivu:
// tmavý motiv = varianta Noc, světlý motiv = varianta Grafit.
const OPENING = "M20 66 C38 48 82 44 104 56 C84 78 44 84 20 66 Z";
const IRIS_STAR = "M63.00 45.00 L64.15 57.23 L67.45 55.55 L65.77 58.85 L74.70 60.00 L65.77 61.15 L67.45 64.45 L64.15 62.77 L63.00 75.00 L61.85 62.77 L58.55 64.45 L60.23 61.15 L51.30 60.00 L60.23 58.85 L58.55 55.55 L61.85 57.23Z";
const UPPER_LID = "M12 66 C30 42 70 34 104 46 C111 48 117 45 122 40 C118 52 110 57 102 56 C80 46 42 48 20 68 Z";
const LOWER_LID = "M22 69 C44 84 80 82 103 58";
const BROW = "M28 34 C48 22 80 20 108 28";

interface Props {
  size?: number;
  /** Logo jednou mrkne (přihlašovací obrazovka). */
  animated?: boolean;
  className?: string;
}

export function Logo({ size = 34, animated = false, className = "" }: Props) {
  const id = `logo-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  return (
    <svg
      viewBox="0 0 128 128"
      width={size}
      height={size}
      className={`logo${animated ? " logo-animated" : ""} ${className}`}
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient id={`${id}-bg`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" className="logo-bg-top" />
          <stop offset="1" className="logo-bg-bottom" />
        </linearGradient>
        <linearGradient id={`${id}-hl`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#fff" stopOpacity="0.22" />
          <stop offset="0.5" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
        <radialGradient id={`${id}-iris`} cx="0.42" cy="0.36" r="0.75">
          <stop offset="0" className="logo-iris-in" />
          <stop offset="1" className="logo-iris-out" />
        </radialGradient>
        <clipPath id={`${id}-eye`}>
          <path d={OPENING} />
        </clipPath>
        <filter id={`${id}-sh`} x="-20%" y="-20%" width="140%" height="160%">
          <feDropShadow dx="0" dy="2.5" stdDeviation="2.5" floodColor="#000" floodOpacity="0.35" />
        </filter>
      </defs>
      <rect width="128" height="128" rx="28.6" fill={`url(#${id}-bg)`} />
      <g transform="translate(0 11)" filter={`url(#${id}-sh)`}>
        <g className="logo-eye">
          <path d={OPENING} fill="#fff" opacity="0.08" />
          <g clipPath={`url(#${id}-eye)`}>
            <circle cx="63" cy="60" r="19" fill={`url(#${id}-iris)`} />
            <path d={IRIS_STAR} className="logo-star" />
            <circle cx="63" cy="60" r="4.5" className="logo-pupil" />
          </g>
          <path d={UPPER_LID} className="logo-lid" />
          <path d={LOWER_LID} fill="none" className="logo-lid-line" strokeWidth="4" strokeLinecap="round" />
        </g>
        <path d={BROW} fill="none" className="logo-lid-line" strokeWidth="5" strokeLinecap="round" />
      </g>
      <rect width="128" height="128" rx="28.6" fill={`url(#${id}-hl)`} />
      <rect x="0.75" y="0.75" width="126.5" height="126.5" rx="27.9" fill="none" stroke="#fff" strokeOpacity="0.16" strokeWidth="1.5" />
    </svg>
  );
}

/** SVG logo compositor — shape + icon + layout + palette. */

const SHAPE_PATHS = {
  circle: null, // special
  hexagon: "M12 2 L20.5 7 L20.5 17 L12 22 L3.5 17 L3.5 7 Z",
  square: "M4 4 H20 V20 H4 Z",
  diamond: "M12 2 L22 12 L12 22 L2 12 Z",
  triangle: "M12 3 L21 20 H3 Z",
  ring: null,
  shield: "M12 2 L20 6 V12 C20 17 16.5 20.5 12 22 C7.5 20.5 4 17 4 12 V6 Z",
  star: "M12 2 L14.5 9 H22 L16 13.5 L18.5 21 L12 16.5 L5.5 21 L8 13.5 L2 9 H9.5 Z",
};

const ICON_PATHS = {
  brain:
    "M9 8a3 3 0 1 1 3-3 M15 8a3 3 0 1 0-3-3 M7 11c-1.5 0-3 1.2-3 3s1 3 3 3h1 M17 11c1.5 0 3 1.2 3 3s-1 3-3 3h-1 M9 17v2 M15 17v2 M12 14v5",
  bolt: "M13 2 L5 13 h6 l-1 9 9-12 h-6 l1-8z",
  atom: "M12 12 m-1.5 0 a1.5 1.5 0 1 0 3 0 a1.5 1.5 0 1 0 -3 0 M5 7 C8 4 16 4 19 7 M5 17 C8 20 16 20 19 17 M4 12 C7 8 17 8 20 12 M4 12 C7 16 17 16 20 12",
  chip: "M8 8h8v8H8z M10 4v3 M14 4v3 M10 17v3 M14 17v3 M4 10h3 M4 14h3 M17 10h3 M17 14h3",
  network:
    "M6 12a1.5 1.5 0 1 0 0.01 0 M18 12a1.5 1.5 0 1 0 0.01 0 M12 6a1.5 1.5 0 1 0 0.01 0 M12 18a1.5 1.5 0 1 0 0.01 0 M7.3 12h9.4 M12 7.3v9.4",
  rocket: "M12 3c2.5 2.5 3.5 7 3.5 10.5L12 18l-3.5-4.5C8.5 10 9.5 5.5 12 3z M9.5 14.5 L7 19 M14.5 14.5 L17 19 M12 8v4",
  eye: "M2.5 12s3.5-5.5 9.5-5.5S21.5 12 21.5 12s-3.5 5.5-9.5 5.5S2.5 12 2.5 12z M12 12m-2.5 0a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0",
  infinity:
    "M7 12c0-1.8 1.2-3 3-3 2.2 0 3.2 3 5 3s3-1.2 3-3-1.2-3-3-3-3.2 3-5 3-3-1.2-3-3 1.2-3 3-3 3 1.2 3 3-1.2 3-3 3c-2.2 0-3.2-3-5-3s-3 1.2-3 3 1.2 3 3 3c2.2 0 3.2-3 5-3s3 1.2 3 3",
  spark: "M12 3l1.2 5.2L18.5 9.5l-5.3 1.2L12 16l-1.2-5.3L5.5 9.5l5.3-1.3z",
  wave: "M3 12c1.5-3.5 3.5-3.5 5 0s3.5 3.5 5 0 3.5-3.5 5 0",
};

function paletteOf(parts, logo) {
  const p = (parts?.palettes || []).find((x) => x.id === logo.palette) || {
    bg: "#0f172a",
    fg: "#38bdf8",
    accent: "#818cf8",
  };
  return {
    bg: logo.custom_bg || p.bg,
    fg: logo.custom_fg || p.fg,
    accent: logo.custom_accent || p.accent,
  };
}

function shapeElement(shape, colors) {
  if (shape === "circle") {
    return `<circle cx="12" cy="12" r="10" fill="${colors.bg}" stroke="${colors.accent}" stroke-width="0.6"/>`;
  }
  if (shape === "ring") {
    return `<circle cx="12" cy="12" r="10" fill="${colors.bg}" stroke="${colors.accent}" stroke-width="1.4"/>
            <circle cx="12" cy="12" r="7" fill="none" stroke="${colors.fg}" stroke-width="0.4" opacity="0.5"/>`;
  }
  const d = SHAPE_PATHS[shape] || SHAPE_PATHS.hexagon;
  return `<path d="${d}" fill="${colors.bg}" stroke="${colors.accent}" stroke-width="0.55" stroke-linejoin="round"/>`;
}

function iconElement(iconId, colors, transform = "") {
  const d = ICON_PATHS[iconId] || ICON_PATHS.brain;
  return `<g transform="${transform}" fill="none" stroke="${colors.fg}" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round">
    <path d="${d}"/>
  </g>`;
}

function monogramEl(text, colors, y = 16.5) {
  const t = (text || "AI").slice(0, 3).toUpperCase();
  return `<text x="12" y="${y}" text-anchor="middle" font-family="IBM Plex Sans, sans-serif" font-weight="700" font-size="5.5" fill="${colors.fg}">${escapeXml(t)}</text>`;
}

function escapeXml(s) {
  return String(s).replace(/[<>&'"]/g, (c) =>
    ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", "'": "&apos;", '"': "&quot;" }[c])
  );
}

let _logoSeq = 0;

export function renderLogoSVG(logo = {}, parts = null, size = 128) {
  const colors = paletteOf(parts, logo);
  const shape = logo.shape || "circle";
  const icon = logo.icon || "brain";
  const layout = logo.layout || "icon_center";
  const mono = logo.monogram || "";
  const gid = `lg${++_logoSeq}`;

  let content = shapeElement(shape, colors);
  // inner glow
  content += `<circle cx="12" cy="12" r="9" fill="url(#${gid})" opacity="0.35"/>`;

  if (layout === "icon_center") {
    content += iconElement(icon, colors, "translate(0,0) scale(1)");
  } else if (layout === "icon_top") {
    content += iconElement(icon, colors, "translate(3.5,1.5) scale(0.7)");
    if (mono) content += monogramEl(mono, colors, 18);
  } else if (layout === "split_horizontal") {
    content += `<line x1="12" y1="5" x2="12" y2="19" stroke="${colors.accent}" stroke-width="0.4" opacity="0.5"/>`;
    content += iconElement(icon, colors, "translate(-3.2,2.5) scale(0.75)");
    content += monogramEl(mono || "AI", colors, 14);
    content = content.replace(
      monogramEl(mono || "AI", colors, 14),
      `<text x="16.5" y="14" text-anchor="middle" font-family="IBM Plex Sans, sans-serif" font-weight="700" font-size="5" fill="${colors.fg}">${escapeXml((mono || "AI").slice(0, 2).toUpperCase())}</text>`
    );
  } else if (layout === "badge") {
    content += `<circle cx="12" cy="12" r="7.5" fill="none" stroke="${colors.fg}" stroke-width="0.35" opacity="0.4"/>`;
    content += iconElement(icon, colors, "translate(2.5,2.2) scale(0.58)");
  } else if (layout === "monogram") {
    content += `<text x="12" y="14.5" text-anchor="middle" font-family="IBM Plex Sans, sans-serif" font-weight="800" font-size="8" fill="${colors.fg}">${escapeXml((mono || "AI").slice(0, 3).toUpperCase())}</text>`;
  } else if (layout === "stacked") {
    content += iconElement(icon, colors, "translate(3.8,1.2) scale(0.68)");
    content += `<path d="M6 17.5 H18" stroke="${colors.accent}" stroke-width="0.7" stroke-linecap="round"/>`;
    content += monogramEl(mono || "AI", colors, 20.2);
  } else {
    content += iconElement(icon, colors);
  }

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="${size}" height="${size}" role="img">
    <defs>
      <radialGradient id="${gid}" cx="35%" cy="30%" r="70%">
        <stop offset="0%" stop-color="${colors.fg}" stop-opacity="0.45"/>
        <stop offset="100%" stop-color="${colors.bg}" stop-opacity="0"/>
      </radialGradient>
    </defs>
    ${content}
  </svg>`;
}

export function mountLogo(el, logo, parts, size) {
  if (!el) return;
  el.innerHTML = renderLogoSVG(logo, parts, size);
}

export function renderFounderAvatar(el, gender = "male") {
  if (!el) return;
  const hair = gender === "female" ? "#a78bfa" : "#38bdf8";
  const shirt = gender === "other" ? "#34d399" : "#818cf8";
  el.innerHTML = `<svg viewBox="0 0 80 100" width="100" height="120" xmlns="http://www.w3.org/2000/svg">
    <rect width="80" height="100" rx="14" fill="#0d1424"/>
    <ellipse cx="40" cy="88" rx="28" ry="18" fill="${shirt}" opacity="0.9"/>
    <circle cx="40" cy="42" r="18" fill="#1e293b" stroke="#334155" stroke-width="2"/>
    <path d="M24 40 Q40 22 56 40" fill="${hair}" opacity="0.85"/>
    <circle cx="33" cy="43" r="2" fill="#e2e8f0"/>
    <circle cx="47" cy="43" r="2" fill="#e2e8f0"/>
    <path d="M34 52 Q40 56 46 52" fill="none" stroke="#94a3b8" stroke-width="1.5" stroke-linecap="round"/>
    <text x="40" y="14" text-anchor="middle" fill="#64748b" font-size="7" font-family="sans-serif">PLACEHOLDER</text>
  </svg>`;
}

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

/* ===== Founder avatar (stylized bust portrait) =====
 * appearance fields: skin, skin_shade, hair_style, hair, hair_shade,
 *   shirt, shirt_shade, accessory, facial_hair, hat, bg, bg2, accent.
 * hair_style: short | messy | curly | gray | bob | bun | ponytail |
 *             spiky | long | balding
 * accessory : none | round_glasses | square_glasses | sun_glasses
 * facial_hair: none | beard | mustache | stubble
 * hat       : none | cap | beanie
 */

const _DEFAULT_FACE = {
  skin: "#f1c7a5",
  skin_shade: "#d9a67e",
  hair_style: "short",
  hair: "#23242b",
  hair_shade: "#15161c",
  shirt: "#334155",
  shirt_shade: "#263143",
  accessory: "none",
  facial_hair: "none",
  hat: "none",
  bg: "#0f172a",
  bg2: "#1e293b",
  accent: "#38bdf8",
};

const _DEFAULT_BY_GENDER = {
  male: _DEFAULT_FACE,
  female: {
    skin: "#f1c7a5",
    skin_shade: "#d9a67e",
    hair_style: "bob",
    hair: "#4a3226",
    hair_shade: "#33211a",
    shirt: "#7e5bd0",
    shirt_shade: "#6544ad",
    accessory: "none",
    facial_hair: "none",
    hat: "none",
    bg: "#2e1065",
    bg2: "#4c1d95",
    accent: "#a78bfa",
  },
  other: {
    skin: "#e0a878",
    skin_shade: "#c48858",
    hair_style: "messy",
    hair: "#1c1d26",
    hair_shade: "#0e0f15",
    shirt: "#0e7c86",
    shirt_shade: "#0a5f66",
    accessory: "none",
    facial_hair: "none",
    hat: "none",
    bg: "#134e4a",
    bg2: "#0f766e",
    accent: "#2dd4bf",
  },
};

let _avSeq = 0;

function normalizeAppearance(appearance, gender) {
  if (appearance && typeof appearance === "object") {
    return { ..._DEFAULT_FACE, ...appearance };
  }
  const g = appearance || gender || "male";
  return _DEFAULT_BY_GENDER[g] || _DEFAULT_BY_GENDER.male;
}

function _avHair(a) {
  const h = a.hair;
  const cap =
    "M31 46 C31 22 69 22 69 46 C69 34 62 30 50 30 C38 30 31 34 31 46 Z";
  switch (a.hair_style) {
    case "messy":
      return (
        `<path d="${cap}" fill="${h}"/>` +
        `<path d="M36 30 L33 23 L40 27 L44 21 L46 27 L52 20 L54 27 L60 22 L60 28 L66 24 L64 31" fill="${h}"/>`
      );
    case "curly":
      return (
        `<path d="${cap}" fill="${h}"/>` +
        `<circle cx="40" cy="24" r="5.5" fill="${h}"/>` +
        `<circle cx="50" cy="20" r="6.5" fill="${h}"/>` +
        `<circle cx="60" cy="24" r="5.5" fill="${h}"/>` +
        `<circle cx="34" cy="31" r="4.5" fill="${h}"/>` +
        `<circle cx="66" cy="31" r="4.5" fill="${h}"/>`
      );
    case "bob":
      return (
        `<path d="${cap}" fill="${h}"/>` +
        `<path d="M31 34 Q27 50 32 64 L38 63 Q34 50 35 40 Z" fill="${h}"/>` +
        `<path d="M69 34 Q73 50 68 64 L62 63 Q66 50 65 40 Z" fill="${h}"/>`
      );
    case "bun":
      return (
        `<path d="${cap}" fill="${h}"/>` +
        `<circle cx="58" cy="17" r="6" fill="${h}"/>` +
        `<path d="M31 40 Q29 30 40 27 Q46 26 52 28 Q42 30 34 40 Z" fill="${a.hair_shade}" opacity="0.5"/>`
      );
    case "spiky":
      return (
        `<path d="${cap}" fill="${h}"/>` +
        `<path d="M34 30 L30 21 L40 26 L44 18 L47 26 L53 17 L55 26 L61 19 L61 28 L66 24 L64 32 Z" fill="${h}"/>`
      );
    case "long":
      return (
        `<path d="${cap}" fill="${h}"/>` +
        `<path d="M31 40 Q25 44 27 52 Q29 58 34 59 L36 54 Q33 48 35 42 Z" fill="${h}"/>` +
        `<path d="M69 40 Q75 44 73 52 Q71 58 66 59 L64 54 Q67 48 65 42 Z" fill="${h}"/>`
      );
    case "balding":
      return (
        `<path d="M32 44 Q37 39 50 38 Q63 39 68 44 Q64 41 50 40 Q36 41 32 44 Z" fill="${h}"/>` +
        `<path d="M32 42 Q30 50 34 55 L37 53 Q35 48 35 43 Z" fill="${h}"/>` +
        `<path d="M68 42 Q70 50 66 55 L63 53 Q65 48 65 43 Z" fill="${h}"/>`
      );
    case "short":
    case "gray":
    default:
      return `<path d="${cap}" fill="${h}"/>`;
  }
}

function _avBackHair(a) {
  const h = a.hair;
  if (a.hair_style === "long") {
    return (
      `<path d="M32 30 Q22 42 24 62 Q25 78 36 80 Q28 66 30 48 Q30 38 33 32 Z" fill="${h}"/>` +
      `<path d="M68 30 Q78 42 76 62 Q75 78 64 80 Q72 66 70 48 Q70 38 67 32 Z" fill="${h}"/>`
    );
  }
  if (a.hair_style === "ponytail") {
    return `<path d="M64 24 Q78 30 74 52 Q70 68 58 74 Q66 62 66 48 Q66 34 62 25 Z" fill="${h}"/>`;
  }
  return "";
}

function _avFace(a) {
  const eye = "#1f2430";
  return (
    `<path d="M38 39 Q42 36 46 39" fill="none" stroke="${a.hair}" stroke-width="1.8" stroke-linecap="round"/>` +
    `<path d="M54 39 Q58 36 62 39" fill="none" stroke="${a.hair}" stroke-width="1.8" stroke-linecap="round"/>` +
    `<ellipse cx="42" cy="45" rx="3" ry="2.3" fill="#ffffff"/>` +
    `<ellipse cx="58" cy="45" rx="3" ry="2.3" fill="#ffffff"/>` +
    `<circle cx="42" cy="45" r="1.4" fill="${eye}"/>` +
    `<circle cx="58" cy="45" r="1.4" fill="${eye}"/>` +
    `<circle cx="42.5" cy="44.5" r="0.5" fill="#ffffff"/>` +
    `<circle cx="58.5" cy="44.5" r="0.5" fill="#ffffff"/>` +
    `<path d="M50 44 L48.5 52 Q50 54 51.5 52 Z" fill="none" stroke="${a.skin_shade}" stroke-width="1.1" stroke-linecap="round"/>` +
    `<path d="M44 58 Q50 62 56 58" fill="none" stroke="#9a5b5b" stroke-width="1.6" stroke-linecap="round"/>` +
    `<ellipse cx="38" cy="52" rx="2.6" ry="1.6" fill="#e8a58c" opacity="0.5"/>` +
    `<ellipse cx="62" cy="52" rx="2.6" ry="1.6" fill="#e8a58c" opacity="0.5"/>`
  );
}

function _avFacialHair(a, g) {
  const h = a.hair;
  if (a.facial_hair === "beard") {
    return (
      `<g clip-path="url(#${g}head)">` +
      `<path d="M30 58 Q50 61 70 58 L70 66 Q60 69 50 69 Q40 69 30 66 Z" fill="${h}" opacity="0.92"/>` +
      `<path d="M43 55 Q50 57 57 55 Q55 59 50 59 Q45 59 43 55 Z" fill="${h}"/>` +
      `<path d="M31 46 Q30 56 34 61 L37 57 Q35 50 35 46 Z" fill="${h}"/>` +
      `<path d="M69 46 Q70 56 66 61 L63 57 Q65 50 65 46 Z" fill="${h}"/>` +
      `</g>`
    );
  }
  if (a.facial_hair === "mustache") {
    return (
      `<g clip-path="url(#${g}head)">` +
      `<path d="M43 55 Q50 57 57 55 Q55 59 50 59 Q45 59 43 55 Z" fill="${h}"/>` +
      `</g>`
    );
  }
  if (a.facial_hair === "stubble") {
    return (
      `<g clip-path="url(#${g}head)">` +
      `<path d="M34 56 Q50 62 66 56" fill="none" stroke="${h}" stroke-width="2" opacity="0.28"/>` +
      `<path d="M40 62 Q50 65 60 62" fill="none" stroke="${h}" stroke-width="1.5" opacity="0.22"/>` +
      `</g>`
    );
  }
  return "";
}

function _avAccessory(a) {
  if (a.accessory === "round_glasses") {
    return (
      `<circle cx="42" cy="45" r="5.5" fill="#e2e8f0" opacity="0.14"/>` +
      `<circle cx="42" cy="45" r="5.5" fill="none" stroke="#1f2937" stroke-width="1.5"/>` +
      `<circle cx="58" cy="45" r="5.5" fill="#e2e8f0" opacity="0.14"/>` +
      `<circle cx="58" cy="45" r="5.5" fill="none" stroke="#1f2937" stroke-width="1.5"/>` +
      `<path d="M47.5 45 Q50 43.5 52.5 45" fill="none" stroke="#1f2937" stroke-width="1.4"/>` +
      `<path d="M36.5 44.5 L30.5 47" stroke="#1f2937" stroke-width="1.4" stroke-linecap="round"/>` +
      `<path d="M63.5 44.5 L69.5 47" stroke="#1f2937" stroke-width="1.4" stroke-linecap="round"/>`
    );
  }
  if (a.accessory === "square_glasses") {
    return (
      `<rect x="36" y="41.5" width="12" height="8" rx="2" fill="#e2e8f0" opacity="0.14"/>` +
      `<rect x="36" y="41.5" width="12" height="8" rx="2" fill="none" stroke="#1f2937" stroke-width="1.5"/>` +
      `<rect x="52" y="41.5" width="12" height="8" rx="2" fill="#e2e8f0" opacity="0.14"/>` +
      `<rect x="52" y="41.5" width="12" height="8" rx="2" fill="none" stroke="#1f2937" stroke-width="1.5"/>` +
      `<path d="M48 45.5 Q50 44.5 52 45.5" fill="none" stroke="#1f2937" stroke-width="1.4"/>` +
      `<path d="M36 43 L30 46" stroke="#1f2937" stroke-width="1.4" stroke-linecap="round"/>` +
      `<path d="M64 43 L70 46" stroke="#1f2937" stroke-width="1.4" stroke-linecap="round"/>`
    );
  }
  if (a.accessory === "sun_glasses") {
    return (
      `<path d="M33 45 Q36 41 42 41 Q47 41 49 45 Q47 49 42 49 Q36 49 33 45 Z" fill="#111827"/>` +
      `<path d="M51 45 Q53 41 58 41 Q64 41 67 45 Q64 49 58 49 Q53 49 51 45 Z" fill="#111827"/>` +
      `<path d="M49 45 L51 45" stroke="#111827" stroke-width="2.4"/>` +
      `<path d="M33 43.5 L30 46.5" stroke="#111827" stroke-width="1.4" stroke-linecap="round"/>` +
      `<path d="M67 43.5 L70 46.5" stroke="#111827" stroke-width="1.4" stroke-linecap="round"/>` +
      `<rect x="35" y="42.5" width="6" height="3" rx="1.5" fill="#ffffff" opacity="0.35" transform="rotate(-14 38 44)"/>` +
      `<rect x="53" y="42.5" width="6" height="3" rx="1.5" fill="#ffffff" opacity="0.35" transform="rotate(-14 56 44)"/>`
    );
  }
  return "";
}

function _avHat(a, g) {
  if (a.hat === "cap") {
    return (
      `<path d="M29 41 C28 24 38 19 50 19 C62 19 72 24 71 41 L70 41 C68 32 60 29 50 29 C40 29 32 32 30 41 Z" fill="#1f2937"/>` +
      `<path d="M29 41 Q50 35 71 41 L71 43 Q50 38 29 43 Z" fill="#111827"/>` +
      `<path d="M50 30.5 L50 42" stroke="#111827" stroke-width="0.8" opacity="0.4"/>`
    );
  }
  if (a.hat === "beanie") {
    return (
      `<path d="M29 42 C27 24 36 20 50 20 C64 20 73 24 71 42 L68 42 C66 32 60 29 50 29 C40 29 34 32 32 42 Z" fill="${a.hair}"/>` +
      `<rect x="42" y="18" width="16" height="4.5" rx="2.2" fill="${a.hair_shade}"/>` +
      `<circle cx="50" cy="19" r="1.6" fill="${a.hair_shade}"/>`
    );
  }
  return "";
}

export function renderFounderAvatar(el, appearance, gender = "male", size) {
  if (!el) return "";
  const a = normalizeAppearance(appearance, gender);
  const w = size || 100;
  const h = size ? Math.round(size * 1.2) : 120;
  const g = `fag${++_avSeq}`;

  const svg = `<svg viewBox="0 0 100 120" width="${w}" height="${h}" role="img" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <linearGradient id="${g}bg" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="${a.bg}"/>
        <stop offset="1" stop-color="${a.bg2}"/>
      </linearGradient>
      <radialGradient id="${g}halo" cx="35%" cy="30%" r="85%">
        <stop offset="0" stop-color="${a.accent}" stop-opacity="0.55"/>
        <stop offset="1" stop-color="${a.bg}" stop-opacity="0"/>
      </radialGradient>
      <linearGradient id="${g}skin" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="${a.skin}"/>
        <stop offset="1" stop-color="${a.skin_shade}"/>
      </linearGradient>
      <linearGradient id="${g}shirt" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="${a.shirt}"/>
        <stop offset="1" stop-color="${a.shirt_shade}"/>
      </linearGradient>
      <clipPath id="${g}head"><ellipse cx="50" cy="46" rx="19" ry="21"/></clipPath>
    </defs>

    <rect width="100" height="120" rx="16" fill="url(#${g}bg)"/>
    <circle cx="50" cy="40" r="34" fill="url(#${g}halo)"/>
    <circle cx="84" cy="12" r="16" fill="${a.accent}" opacity="0.12"/>
    <circle cx="14" cy="104" r="22" fill="${a.accent}" opacity="0.08"/>

    <path d="M16 120 C14 92 30 80 42 78 L58 78 C70 80 86 92 84 120 Z" fill="url(#${g}shirt)"/>
    <path d="M42 78 L58 78 L50 88 Z" fill="#ffffff" opacity="0.18"/>
    <path d="M40 78 L50 93 L60 78 L58 78 L50 88 L42 78 Z" fill="${a.shirt_shade}" opacity="0.55"/>
    <rect x="44" y="56" width="12" height="28" rx="5" fill="${a.skin_shade}"/>
    <path d="M46 60 L54 60 L50 84 Z" fill="${a.skin_shade}" opacity="0.6"/>

    ${_avBackHair(a)}

    <ellipse cx="50" cy="46" rx="19" ry="21" fill="url(#${g}skin)"/>
    <ellipse cx="30.5" cy="49" rx="4.5" ry="7" fill="${a.skin_shade}"/>
    <ellipse cx="69.5" cy="49" rx="4.5" ry="7" fill="${a.skin_shade}"/>
    <ellipse cx="30.5" cy="49" rx="2" ry="3.4" fill="${a.skin}" opacity="0.65"/>
    <ellipse cx="69.5" cy="49" rx="2" ry="3.4" fill="${a.skin}" opacity="0.65"/>

    ${_avFace(a)}
    ${_avFacialHair(a, g)}

    <g>${_avHair(a)}</g>
    ${_avAccessory(a)}
    ${_avHat(a, g)}
  </svg>`;

  el.innerHTML = svg;
  return svg;
}

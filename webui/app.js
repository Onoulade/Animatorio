import { api } from "./api-client.js";

"use strict";

const HANDLE_HIT_PX = 9;

const el = (id) => document.getElementById(id);

const statusEl = el("status");
const assetPathEl = el("asset-path");
const layerListEl = el("layer-list");
const isolateToggle = el("isolate-toggle");
const smoothingToggle = el("smoothing-toggle");
const overlayToggle = el("overlay-toggle");
const playToggle = el("play-toggle");
const zoomLabel = el("zoom-label");
const canvas = el("stage");
const ctx = canvas.getContext("2d");
const geometryPanel = el("geometry-panel");
const secondaryPanel = el("secondary-panel");
const genericPanel = el("generic-panel");
const commonPanel = el("common-panel");
const rawJsonEl = el("raw-json");
const jsonErrorEl = el("json-error");
const addMotionTypeSelect = el("add-motion-type");
const addLayerBtn = el("add-layer-btn");
const dirtyIndicatorEl = el("dirty-indicator");
const animationSpeedInput = el("animation-speed-input");
const animationSpeedNote = el("animation-speed-note");
const appShell = el("app-shell");
const emptyStateEl = el("empty-state");
const layerEmptyEl = el("layer-empty");
const inspectorEmptyEl = el("inspector-empty");
const inspectorTitleEl = el("inspector-title");
const layerCountEl = el("layer-count");
const assetSectionEl = el("asset-section");
const layerSectionEl = el("layer-section");
const layerSectionSubtitleEl = el("layer-section-subtitle");
const assetFrameCountEl = el("asset-frame-count");
const assetSheetColumnsEl = el("asset-sheet-columns");
const assetSheetSizeEl = el("asset-sheet-size");
const assetLightingEnabledEl = el("asset-lighting-enabled");
const assetLightingDirectionEl = el("asset-lighting-direction");
const assetLightingStrengthEl = el("asset-lighting-strength");
const assetLightingStrengthValueEl = el("asset-lighting-strength-value");
const assetLightingAmbientEl = el("asset-lighting-ambient");
const assetLightingAmbientValueEl = el("asset-lighting-ambient-value");

const MOTION_LABELS = {
  mechanical_rotor: "Rotor / fan",
  mechanical_gear: "Gear / cog",
  vertical_gear: "Edge-on gear",
  source_occluder: "Foreground occluder",
  vibration: "Vibration",
  gauge: "Gauge needle",
  surface_scan: "Surface scan",
  sweep: "Light sweep",
  orbit_glint: "Orbit glint",
  signal: "Signal",
  pulse: "Pulse",
  chase: "Chase lights",
  steam: "Steam",
};

// Default frame count (see asset_store.FRAME_COUNT on the Python side).
// Can be overridden per asset via the Asset inspector section.
const DEFAULT_FRAME_COUNT = 24;
const MAX_FRAME_COUNT = 64;
const DEFAULT_LIGHTING = {
  enabled: true,
  direction_degrees: 35,
  strength: 0.24,
  ambient: 0.82,
};

const state = {
  // The single currently-open asset's full data (name/source/output/size/
  // motions/animation_speed) and the file it will save to.
  asset: null,
  assetPath: null,
  // The full layer list for the currently open sprite, including any
  // unsaved add/remove/edit. Switching layers just points state.motion at a
  // different entry in this same array -- nothing is discarded until the
  // user opens a different asset (with confirmation) or explicitly saves/
  // reloads.
  workingMotions: [],
  motionIndex: 0,
  motion: null,
  // Per-asset animation speed, in-editor. Not a layer property --
  // one value per asset, persisted into the asset JSON on save.
  animationSpeed: 0.25,
  // Per-asset frame count, persisted into the asset JSON. Sheet columns are
  // derived from this count.
  frameCount: 24,
  lighting: { ...DEFAULT_LIGHTING },
  baseScale: 1,
  zoom: 1,
  frameImages: [],
  playing: true,
  pausedIndex: 0,
  dragging: null,
  dragOrigin: null,
  selectedHandleId: null,
  handles: [],
  requestSeq: 0,
  refreshCallbacks: [],
  verticalGearAdvanced: false,
  gaugeAdvanced: false,
};

function refreshGeometryInputs() {
  for (const callback of state.refreshCallbacks) callback();
}

function clamp(value, lo, hi) {
  return Math.max(lo, Math.min(hi, value));
}

function isPrime(value) {
  if (value < 2) return false;
  for (let divisor = 2; divisor * divisor <= value; divisor += 1) {
    if (value % divisor === 0) return false;
  }
  return true;
}

function validFrameCount(value) {
  return Number.isInteger(value) && value >= 1 && value <= MAX_FRAME_COUNT && !isPrime(value);
}

function sheetColumns(frameCount) {
  const divisors = [];
  for (let value = 1; value <= frameCount; value += 1) {
    if (frameCount % value === 0) divisors.push(value);
  }
  return divisors.sort((left, right) => {
    const targetDistance = Math.abs(left - 6) - Math.abs(right - 6);
    if (targetDistance !== 0) return targetDistance;
    const squareRoot = Math.sqrt(frameCount);
    return Math.abs(left - squareRoot) - Math.abs(right - squareRoot);
  })[0];
}

function round2(value) {
  return Math.round(value * 100) / 100;
}
function setStatus(text, kind) {
  statusEl.textContent = text;
  statusEl.className = "status" + (kind ? " " + kind : "");
}

function updateEditorAvailability() {
  const hasAsset = Boolean(state.asset);
  appShell.dataset.hasAsset = hasAsset ? "true" : "false";
  emptyStateEl.classList.toggle("hidden", hasAsset);
  document.querySelectorAll("[data-requires-asset]").forEach((control) => {
    control.disabled = !hasAsset;
  });
}

// ------------------------------------------------------------------ asset

function pathDirname(path) {
  const idx = path.lastIndexOf("/");
  return idx >= 0 ? path.slice(0, idx) : path;
}

function pathBasename(path) {
  return path.split("/").pop();
}

function baseNameNoExt(path) {
  const name = pathBasename(path);
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(0, dot) : name;
}

function updateAssetPathLabel() {
  assetPathEl.textContent = state.assetPath ? pathBasename(state.assetPath) : "No asset open";
  assetPathEl.title = state.assetPath || "";
}

// Resets the editor to its startup state, before any asset is open. Every
// panel must tolerate "nothing selected" since selectLayer() otherwise
// assumes an asset already exists.
function clearAssetView() {
  state.asset = null;
  state.assetPath = null;
  state.workingMotions = [];
  state.motionIndex = -1;
  state.motion = null;
  state.frameCount = DEFAULT_FRAME_COUNT;
  state.lighting = { ...DEFAULT_LIGHTING };
  state.frameImages = [];
  layerListEl.innerHTML = "";
  geometryPanel.innerHTML = "";
  secondaryPanel.innerHTML = "";
  genericPanel.innerHTML = "";
  commonPanel.innerHTML = "";
  rawJsonEl.value = "";
  canvas.width = 0;
  canvas.height = 0;
  layerCountEl.textContent = "0";
  layerEmptyEl.classList.add("visible");
  inspectorEmptyEl.classList.add("visible");
  inspectorTitleEl.textContent = "Inspector";
  assetSectionEl.classList.add("hidden");
  layerSectionEl.classList.remove("hidden");
  layerSectionSubtitleEl.textContent = "Select a layer";
  updateAssetPathLabel();
  updateEditorAvailability();
  updateDirtyIndicator();
  setStatus("Ready", "ok");
}

function iconButton(label, title, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "icon-btn";
  button.textContent = label;
  button.title = title;
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    onClick();
  });
  return button;
}

function renderLayerList() {
  layerListEl.innerHTML = "";
  layerCountEl.textContent = String(state.workingMotions.length);
  layerEmptyEl.classList.toggle("visible", Boolean(state.asset) && state.workingMotions.length === 0);
  state.workingMotions
    .map((motion, index) => ({ motion, index }))
    .reverse()
    .forEach(({ motion, index }, displayIndex) => {
      const layerRow = document.createElement("div");
      layerRow.className = "layer-row" + (index === state.motionIndex ? " selected" : "");

      const body = document.createElement("div");
      body.className = "layer-row-body";
      const title = document.createElement("span");
      title.className = "layer-row-title";
      title.textContent = motion.label || MOTION_LABELS[motion.type] || motion.type;
      const meta = document.createElement("span");
      meta.className = "layer-row-meta";
      meta.textContent = `${String(displayIndex + 1).padStart(2, "0")} · ${motion.type}`;
      body.append(title, meta);
      body.addEventListener("click", () => selectLayer(index));
      layerRow.appendChild(body);

      const actions = document.createElement("div");
      actions.className = "layer-row-actions";
      const upBtn = iconButton("Back", "Move behind", () => moveLayer(index, -1));
      upBtn.disabled = index === 0;
      const downBtn = iconButton("Front", "Move in front", () => moveLayer(index, 1));
      downBtn.disabled = index === state.workingMotions.length - 1;
      const duplicateBtn = iconButton("Copy", "Duplicate layer", () => duplicateLayer(index));
      const deleteBtn = iconButton("Delete", "Delete layer", () => deleteLayer(index));
      deleteBtn.classList.add("danger");
      actions.append(upBtn, downBtn, duplicateBtn, deleteBtn);
      layerRow.appendChild(actions);

      layerListEl.appendChild(layerRow);
    });
}

function assetAnimationSpeed(asset) {
  return asset.animation_speed ?? 0.25;
}

function assetLighting(asset) {
  return { ...DEFAULT_LIGHTING, ...(asset?.lighting || {}) };
}

// animation_speed is frames advanced per tick, 60 ticks/sec. It controls
// preview timing only; the user can apply the generated sheet however they
// like in the target game or application.
function frameIntervalMs() {
  return 1000 / (60 * (state.animationSpeed || 0.25));
}

function updateAnimationSpeedNote() {
  const speed = state.animationSpeed || 0.25;
  const frameCount = state.frameCount || DEFAULT_FRAME_COUNT;
  const seconds = frameCount / (60 * speed);
  animationSpeedNote.textContent =
    `${frameCount} frames, ≈${seconds.toFixed(2)}s / loop`;
}

function hasUnsavedChanges() {
  if (!state.asset) return false;
  if (JSON.stringify(state.workingMotions) !== JSON.stringify(state.asset.motions)) return true;
  if (Math.abs(state.animationSpeed - assetAnimationSpeed(state.asset)) > 1e-9) return true;
  if (state.frameCount !== (state.asset.frame_count ?? DEFAULT_FRAME_COUNT)) return true;
  return JSON.stringify(state.lighting) !== JSON.stringify(assetLighting(state.asset));
}

function updateDirtyIndicator() {
  const dirty = hasUnsavedChanges();
  dirtyIndicatorEl.textContent = dirty ? "● Unsaved changes on this sprite" : "";
  dirtyIndicatorEl.className = "muted-note" + (dirty ? " dirty" : "");
}

function preferredMotionIndex(asset) {
  const index = asset.motions.findIndex(
    (motion) =>
      motion.type === "mechanical_rotor" ||
      motion.type === "mechanical_gear" ||
      motion.type === "vertical_gear" ||
      motion.type === "vibration" ||
      motion.type === "gauge"
  );
  return index >= 0 ? index : 0;
}

// ------------------------------------------------------------- plane model

function getPlanes(motion) {
  const planes = [];
  if (motion.type === "mechanical_rotor") {
    planes.push({ key: "main", label: "Rotor face", centerKey: "center", basisKey: "plane_basis", color: "#d98f3a" });
    if (motion.source_hub_basis || motion.hub_center) {
      planes.push({
        key: "hub",
        label: "Hub",
        centerKey: "hub_center",
        centerFallback: "center",
        basisKey: "source_hub_basis",
        color: "#6fb4d9",
        locked: true,
      });
    }
  } else if (motion.type === "mechanical_gear") {
    planes.push({ key: "main", label: "Gear face", centerKey: "center", basisKey: "plane_basis", color: "#d98f3a" });
    if (motion.source_center_basis || motion.source_center) {
      planes.push({
        key: "sourceCenter",
        label: "Center plate",
        centerKey: "source_center",
        centerFallback: "center",
        basisKey: "source_center_basis",
        color: "#6fb4d9",
        locked: true,
      });
    }
  } else if (motion.type === "gauge") {
    planes.push({ key: "main", label: "Gauge face", centerKey: "center", basisKey: "plane_basis", color: "#ef6d87" });
  }
  return planes;
}

function getPlaneCenter(motion, plane) {
  return motion[plane.centerKey] || (plane.centerFallback ? motion[plane.centerFallback] : null) || [0, 0];
}

function setPlaneCenter(motion, plane, xy) {
  motion[plane.centerKey] = xy;
}

function getPlaneBasis(motion, plane) {
  return motion[plane.basisKey] || [
    [10, 0],
    [0, 10],
  ];
}

// ------------------------------------------------------------- shape model
//
// Non-rotor/gear motions (surface_scan, sweep, orbit_glint, signal, pulse,
// chase, steam, ...) don't have a plane_basis -- they're positioned by a
// polygon, an axis-aligned bbox, a list of points, or a single center/origin.
// bbox takes priority over polygon because a few sweep entries carry both:
// the bbox drives the actual animated travel path, the polygon is only an
// extra clip mask, so bbox is the geometry worth dragging.

function getShapeSpec(motion) {
  if (motion.type === "source_occluder" && motion.shape === "ellipse_ring") {
    return { kind: "ellipseRing" };
  }
  if (Array.isArray(motion.bbox)) return { kind: "bbox" };
  if (Array.isArray(motion.polygon)) return { kind: "polygon" };
  if (Array.isArray(motion.points)) {
    return { kind: "points", radiusKey: Array.isArray(motion.radius) ? "radius" : null };
  }
  if (Array.isArray(motion.center)) {
    return { kind: "point", key: "center", radiusKey: Array.isArray(motion.radius) ? "radius" : null };
  }
  if (Array.isArray(motion.origin)) return { kind: "point", key: "origin" };
  return null;
}

function normalizeBbox(motion) {
  const [x0, y0, x1, y1] = motion.bbox;
  motion.bbox = [Math.min(x0, x1), Math.min(y0, y1), Math.max(x0, x1), Math.max(y0, y1)];
}

// An independent, arbitrary-vertex-count clip shape -- distinct from
// whatever field drives the motion's own path/geometry, since that one is
// sometimes constrained (surface_scan's `polygon` must stay a 4-point quad
// for scan_segment()'s interpolation). Field name matches what
// generate_animations.py's surface_mask() actually reads per motion type:
// surface_scan/pulse use the dedicated `mask_polygon` override, while
// sweep/orbit_glint already treat their own optional `polygon` as a free-form
// mask (their path comes from `bbox` instead), so no separate field exists.
function getMaskFieldKey(motion) {
  if (motion.type === "surface_scan" || motion.type === "vertical_gear" || motion.type === "pulse") {
    return "mask_polygon";
  }
  if (motion.type === "sweep" || motion.type === "orbit_glint") return "polygon";
  return null;
}

// ------------------------------------------------------------ new layers

const MOTION_TYPES = [
  "mechanical_rotor",
  "mechanical_gear",
  "vertical_gear",
  "source_occluder",
  "vibration",
  "gauge",
  "surface_scan",
  "sweep",
  "orbit_glint",
  "signal",
  "pulse",
  "chase",
  "steam",
];

function getDefaultMotion(type, size) {
  const cx = round2(size[0] / 2);
  const cy = round2(size[1] / 2);
  switch (type) {
    case "mechanical_rotor":
      // Hub concentric with the rotor face by default -- a separately
      // positioned hub is the exception (a few assets set hub_center
      // explicitly), not the starting point.
      return {
        type: "mechanical_rotor",
        center: [cx, cy],
        plane_basis: [
          [20, 0],
          [0, 20],
        ],
        aperture_radius: [20, 20],
        aperture_bbox: [cx - 20, cy - 20, cx + 20, cy + 20],
        hub_center: [cx, cy],
        source_hub_basis: [
          [8, 0],
          [0, 8],
        ],
        hub_bbox: [cx - 8, cy - 8, cx + 8, cy + 8],
        blade_count: 8,
        base_angle: 0,
        blade_color: [90, 85, 70],
        aperture_feather: 0.6,
        hub_feather: 0.6,
        supersample: 8,
      };
    case "mechanical_gear":
      return {
        type: "mechanical_gear",
        center: [cx, cy],
        plane_basis: [
          [20, 0],
          [0, 20],
        ],
        outer_radius: [20, 20],
        inner_radius: [13, 13],
        inner_fraction: 0.65,
        tooth_count: 10,
        base_angle: 0,
        root_fraction: 0.88,
        tooth_tip_fraction: 0.22,
        gear_color: [112, 88, 51],
        gear_thickness_fraction: 0.14,
        thickness_direction: [0.55, 0.83],
        thickness_brightness: 0.46,
        thickness_edge_highlight: 0.14,
        fill_style: "solid",
        fill_count: 5,
        fill_width_fraction: 0.24,
        body_hub_fraction: 0.24,
        body_rim_width: 0.1,
        hole_ring_fraction: 0.53,
        hole_radius_fraction: 0.12,
        // Painted disc by default, not a source-art reveal: a brand-new gear
        // on an existing sprite has nothing gear-hub-like drawn under it, so
        // revealing source pixels there would just show background/hole.
        center_cap_bbox: [round2(cx - 9), round2(cy - 9), round2(cx + 9), round2(cy + 9)],
        center_cap_color: [112, 88, 51],
        source_tooth_material: true,
        source_albedo_blend: 0.7,
        albedo_tint_strength: 0.7,
        source_material_blend: 0.16,
        material_blur: 2.0,
        aperture_feather: 0.65,
        supersample: 8,
      };
    case "vertical_gear":
      return {
        type: "vertical_gear",
        // A projective strip, ordered top-left, top-right, bottom-right,
        // bottom-left. The slight convergence makes the editable perspective
        // obvious without assuming the final building camera angle.
        polygon: [
          [round2(cx - 7), round2(cy - 30)],
          [round2(cx + 7), round2(cy - 27)],
          [round2(cx + 6), round2(cy + 28)],
          [round2(cx - 6), round2(cy + 31)],
        ],
        middle: [cx, cy],
        axis: "y",
        tooth_count: 8,
        arc_start_degrees: 90,
        arc_end_degrees: 90,
        direction: 1,
        pitches_per_loop: 1,
        phase: 0,
        source_tooth_material: true,
        source_material_blend: 0.82,
        source_detail_strength: 0.88,
        material_blur: 1.6,
        tooth_width_fraction: 0.52,
        tooth_depth_fraction: 0.42,
        outer_edge: "start",
        silhouette_softness: 0.025,
        side_depth_fraction: 0.2,
        root_face_brightness: 0.64,
        cavity_brightness: 0.28,
        side_face_brightness: 0.56,
        face_texture_strength: 0.1,
        root_shadow_strength: 0.24,
        tip_highlight_strength: 0.18,
        edge_softness: 0.065,
        highlight_strength: 0.18,
        shadow_strength: 0.24,
        groove_strength: 0.075,
        tooth_top_light: 0.018,
        groove_visibility_power: 0.62,
        side_visibility_power: 0.58,
        side_face_strength: 0.26,
        side_shadow_strength: 0.34,
        side_gap_shadow: 0.1,
        edge_material_floor: 0.22,
        edge_occlusion_power: 0.72,
        light_direction: 1,
        aperture_feather: 0.55,
        supersample: 6,
      };
    case "source_occluder":
      return {
        type: "source_occluder",
        shape: "polygon",
        polygon: [
          [round2(cx - 18), round2(cy - 12)],
          [round2(cx + 18), round2(cy - 12)],
          [round2(cx + 18), round2(cy + 12)],
          [round2(cx - 18), round2(cy + 12)],
        ],
        feather: 0.35,
      };
    case "vibration":
      return {
        type: "vibration",
        polygon: [
          [round2(cx - 18), round2(cy - 15)],
          [round2(cx + 18), round2(cy - 15)],
          [round2(cx + 18), round2(cy + 15)],
          [round2(cx - 18), round2(cy + 15)],
        ],
        pivot: [cx, cy],
        amplitude: [0.65, 1.0],
        cycles_per_loop: 3,
        waveform: "motor",
        phase: 0,
        y_phase_offset: 0,
        rotation_degrees: 0.25,
        rotation_phase_offset: 0,
        feather: 0.65,
        background_mode: "source",
        cavity_brightness: 0.48,
        cavity_blur: 1.2,
        supersample: 6,
      };
    case "gauge":
      return {
        type: "gauge",
        label: "Gauge needle",
        center: [cx, cy],
        plane_basis: [
          [16, 0],
          [0, 13],
        ],
        minimum_angle_degrees: -150,
        maximum_angle_degrees: -30,
        needle_length: 0.78,
        tail_length: 0.12,
        needle_width: 0.055,
        tip_width: 0.012,
        pivot_radius: 0.1,
        waveform: "sine",
        cycles_per_loop: 1,
        phase: 0,
        reverse: false,
        background_enabled: true,
        face_color: [57, 51, 42],
        face_alpha: 255,
        rim_color: [137, 102, 57],
        rim_shadow_color: [48, 38, 29],
        rim_width: 0.09,
        tick_color: [225, 204, 153],
        tick_count: 11,
        major_tick_every: 5,
        tick_length: 0.105,
        tick_margin: 0.055,
        tick_width: 0.75,
        needle_color: [196, 68, 49],
        edge_color: [67, 31, 24],
        highlight_color: [245, 163, 118],
        pivot_color: [116, 91, 61],
        shadow_offset: [0.8, 1.0],
        shadow_alpha: 115,
        shadow_blur: 0.55,
        clip_to_face: true,
        face_fraction: 1,
        aperture_feather: 0.5,
        supersample: 6,
      };
    case "surface_scan":
      return {
        type: "surface_scan",
        polygon: [
          [cx - 20, cy - 15],
          [cx + 20, cy - 15],
          [cx + 20, cy + 15],
          [cx - 20, cy + 15],
        ],
        axis: "y",
        color: [255, 230, 190],
        alpha: 60,
        width: 2,
        blur: 1.0,
      };
    case "sweep":
      return {
        type: "sweep",
        bbox: [cx - 20, cy - 20, cx + 20, cy + 20],
        axis: "x",
        color: [80, 190, 255],
        alpha: 100,
        width: 2,
        blur: 1.5,
      };
    case "orbit_glint":
      return {
        type: "orbit_glint",
        bbox: [cx - 25, cy - 25, cx + 25, cy + 25],
        turns: 1,
        count: 3,
        dot_radius: 2.5,
        alpha: 60,
        blur: 1.2,
      };
    case "signal":
      return {
        type: "signal",
        origin: [cx, cy],
        travel: 20,
        count: 2,
        alpha: 55,
        color: [110, 200, 255],
        start_angle: 200,
        end_angle: 340,
      };
    case "pulse":
      return {
        type: "pulse",
        center: [cx, cy],
        radius: [6, 6],
        color: [255, 190, 70],
        alpha: 110,
        blur: 4,
      };
    case "chase":
      return {
        type: "chase",
        points: [
          [cx - 15, cy, 255, 190, 70],
          [cx, cy, 255, 190, 70],
          [cx + 15, cy, 255, 190, 70],
        ],
        radius: [3, 3],
        alpha: 110,
        blur: 2,
      };
    case "steam":
      return {
        type: "steam",
        origin: [cx, cy],
        rise: 25,
        drift: 5,
        count: 4,
        radius: 3,
        alpha: 40,
        blur: 2,
      };
    default:
      throw new Error("unknown motion type: " + type);
  }
}

// -------------------------------------------------------------- selection

// Loads a freshly opened asset (from open-file, open-from-image, or reload)
// into the working state. Callers are responsible for confirming discard of
// any prior unsaved edits before calling this.
function applyOpenedAsset(asset, path) {
  state.asset = asset;
  state.assetPath = path;
  state.workingMotions = JSON.parse(JSON.stringify(asset.motions));
  state.frameCount = asset.frame_count ?? DEFAULT_FRAME_COUNT;
  state.lighting = assetLighting(asset);

  state.animationSpeed = assetAnimationSpeed(asset);
  animationSpeedInput.value = state.animationSpeed;
  updateAnimationSpeedNote();
  updateAssetPathLabel();
  updateEditorAvailability();
  buildAssetSection();

  const [w, h] = asset.size;
  state.baseScale = clamp(560 / Math.max(w, h), 1, 6);
  state.zoom = 1;
  updateZoomLabel();

  const index = state.workingMotions.length > 0 ? preferredMotionIndex(asset) : -1;
  selectLayer(index);
}

function selectLayer(index) {
  state.motionIndex = index;
  // Direct reference into workingMotions (not a clone): every edit made
  // through the panels/canvas mutates this same object in place, so it's
  // already "saved" into the working set the instant you switch away.
  state.motion = index >= 0 ? state.workingMotions[index] : null;
  inspectorEmptyEl.classList.toggle("visible", !state.motion);
  inspectorTitleEl.textContent = state.motion
    ? state.motion.label || MOTION_LABELS[state.motion.type] || state.motion.type
    : "Inspector";
  if (state.motion) {
    layerSectionEl.classList.remove("hidden");
    layerSectionSubtitleEl.textContent = state.motion.label || MOTION_LABELS[state.motion.type] || state.motion.type;
  } else {
    layerSectionEl.classList.add("hidden");
    layerSectionSubtitleEl.textContent = "Select a layer";
  }
  state.selectedHandleId = null;
  renderLayerList();
  resizeCanvas();
  buildPanels();
  syncRawJson();
  scheduleRender(true);
  updateDirtyIndicator();
}

function addLayer() {
  const type = addMotionTypeSelect.value;
  const motion = getDefaultMotion(type, state.asset.size);
  state.workingMotions.push(motion);
  selectLayer(state.workingMotions.length - 1);
}

function duplicateLayer(index) {
  // Deep clone, not a shared reference -- the copy must edit independently
  // of the original, same as every other entry in workingMotions.
  const clone = JSON.parse(JSON.stringify(state.workingMotions[index]));
  const insertAt = index + 1;
  state.workingMotions.splice(insertAt, 0, clone);
  selectLayer(insertAt);
}

function deleteLayer(index) {
  if (!confirm("Delete this layer from the working set? (Reload from disk to bring it back before saving.)")) return;
  state.workingMotions.splice(index, 1);
  let nextIndex = state.motionIndex;
  if (index === state.motionIndex) nextIndex = Math.min(index, state.workingMotions.length - 1);
  else if (index < state.motionIndex) nextIndex -= 1;
  selectLayer(nextIndex);
}

function moveLayer(index, delta) {
  // Render order is purely array order (generate_animations.py paints
  // motions[] front-to-back in sequence) -- there's no separate z-index
  // field, so "which layer occludes another" is decided entirely by
  // reordering entries here.
  const to = index + delta;
  if (to < 0 || to >= state.workingMotions.length) return;
  const [moved] = state.workingMotions.splice(index, 1);
  state.workingMotions.splice(to, 0, moved);
  let nextIndex = state.motionIndex;
  if (index === state.motionIndex) nextIndex = to;
  else if (to <= state.motionIndex && index > state.motionIndex) nextIndex += 1;
  else if (to >= state.motionIndex && index < state.motionIndex) nextIndex -= 1;
  selectLayer(nextIndex);
}

// ------------------------------------------------------------------ canvas

function resizeCanvas() {
  if (!state.asset) {
    canvas.width = 0;
    canvas.height = 0;
    return;
  }
  const [w, h] = state.asset.size;
  const scale = state.baseScale * state.zoom;
  const dpr = window.devicePixelRatio || 1;
  canvas.style.width = `${w * scale}px`;
  canvas.style.height = `${h * scale}px`;
  canvas.width = Math.round(w * scale * dpr);
  canvas.height = Math.round(h * scale * dpr);
}

function worldScale() {
  return state.baseScale * state.zoom * (window.devicePixelRatio || 1);
}

function gaugePlanePoint(motion, angleDegrees, radius) {
  const angle = angleDegrees * Math.PI / 180;
  const center = motion.center || [0, 0];
  const basis = motion.plane_basis || [[10, 0], [0, 10]];
  const u = Math.cos(angle) * radius;
  const v = Math.sin(angle) * radius;
  return [
    center[0] + basis[0][0] * u + basis[1][0] * v,
    center[1] + basis[0][1] * u + basis[1][1] * v,
  ];
}

function gaugeLocalPoint(motion, x, y) {
  const center = motion.center || [0, 0];
  const basis = motion.plane_basis || [[10, 0], [0, 10]];
  const dx = x - center[0];
  const dy = y - center[1];
  const determinant = basis[0][0] * basis[1][1] - basis[1][0] * basis[0][1];
  if (Math.abs(determinant) < 0.000001) return [1, 0];
  return [
    (dx * basis[1][1] - dy * basis[1][0]) / determinant,
    (-dx * basis[0][1] + dy * basis[0][0]) / determinant,
  ];
}

function gearMaximumAxis(motion) {
  const basis = motion.plane_basis || [[10, 0], [0, 10]];
  return Math.max(0.001, Math.hypot(basis[0][0], basis[0][1]), Math.hypot(basis[1][0], basis[1][1]));
}

function gearThicknessVector(motion) {
  const direction = motion.thickness_direction || [0.55, 0.83];
  const directionLength = Math.hypot(direction[0], direction[1]);
  const unit = directionLength > 0.000001
    ? [direction[0] / directionLength, direction[1] / directionLength]
    : [0.55, 0.83];
  const length = gearMaximumAxis(motion) * Math.max(0, motion.gear_thickness_fraction ?? 0);
  return [unit[0] * length, unit[1] * length];
}

function setGearThicknessVector(motion, vector) {
  const length = Math.hypot(vector[0], vector[1]);
  motion.gear_thickness_fraction = round2(clamp(length / gearMaximumAxis(motion), 0, 0.6));
  if (length > 0.000001) {
    motion.thickness_direction = [round2(vector[0] / length), round2(vector[1] / length)];
  }
}

function gearThicknessHandleVector(motion) {
  const vector = gearThicknessVector(motion);
  if (Math.hypot(vector[0], vector[1]) >= 0.75) return vector;
  const direction = motion.thickness_direction || [0.55, 0.83];
  const length = Math.max(0.000001, Math.hypot(direction[0], direction[1]));
  // Keep a zero-thickness cog editable instead of hiding its endpoint under
  // the gear-center handle. Dragging this short dashed guide enables depth.
  return [direction[0] / length * 3.5, direction[1] / length * 3.5];
}

// --------------------------------------------------------- rectangle model
//
// Cogs and fans are always placed as an upright, non-inclined rectangle
// (position + width/height) -- no independent skew per axis. Anything
// concentric with that rectangle (a fan's hub, a gear's center fill) is
// locked to the same center and the same width:height ratio, exposed as a
// single size slider instead of its own position/basis pair. This trades
// the old fully-general 2x2 basis editing (which let a hub drift off-center
// or stretch out of round) for the common case that's actually used --
// hand-editing plane_basis/source_center_basis/etc. in the raw JSON panel
// remains the escape hatch for the rare asset needing true perspective skew.

function planeExtent(basis) {
  return [Math.abs(basis[0][0]), Math.abs(basis[1][1])];
}

function fillRatioFromExtent(extent, mainExtent) {
  const rx = mainExtent[0] > 0.0001 ? extent[0] / mainExtent[0] : 0.4;
  const ry = mainExtent[1] > 0.0001 ? extent[1] / mainExtent[1] : 0.4;
  return clamp(round2((rx + ry) / 2), 0.05, 0.95);
}

function currentFillRatio(motion, plane, mainPlane) {
  const mainExtent = planeExtent(getPlaneBasis(motion, mainPlane));
  const extent = planeExtent(getPlaneBasis(motion, plane));
  return fillRatioFromExtent(extent, mainExtent);
}

function applyFillRatio(motion, plane, mainPlane, ratio) {
  ratio = clamp(round2(ratio), 0.05, 0.95);
  const mainExtent = planeExtent(getPlaneBasis(motion, mainPlane));
  setPlaneCenter(motion, plane, getPlaneCenter(motion, mainPlane));
  motion[plane.basisKey] = [
    [round2(mainExtent[0] * ratio), 0],
    [0, round2(mainExtent[1] * ratio)],
  ];
}

function currentCapRatio(motion) {
  const mainExtent = planeExtent(motion.plane_basis || [[10, 0], [0, 10]]);
  const rx = (motion.center_cap_bbox[2] - motion.center_cap_bbox[0]) / 2;
  const ry = (motion.center_cap_bbox[3] - motion.center_cap_bbox[1]) / 2;
  return fillRatioFromExtent([rx, ry], mainExtent);
}

function applyCapRatio(motion, ratio) {
  ratio = clamp(round2(ratio), 0.05, 0.95);
  const mainExtent = planeExtent(motion.plane_basis || [[10, 0], [0, 10]]);
  const [cx, cy] = motion.center;
  const rx = round2(mainExtent[0] * ratio);
  const ry = round2(mainExtent[1] * ratio);
  motion.center_cap_bbox = [round2(cx - rx), round2(cy - ry), round2(cx + rx), round2(cy + ry)];
}

function computeHandles() {
  const handles = [];
  const motion = state.motion;
  if (!motion) return handles;

  if (motion.type === "gauge") {
    const plane = getPlanes(motion)[0];
    const center = getPlaneCenter(motion, plane);
    handles.push({ id: plane.key + ":center", x: center[0], y: center[1], kind: "center", plane });
    const basis = getPlaneBasis(motion, plane);
    handles.push({
      id: plane.key + ":basisX",
      x: center[0] + basis[0][0],
      y: center[1] + basis[0][1],
      kind: "basisX",
      plane,
    });
    handles.push({
      id: plane.key + ":basisY",
      x: center[0] + basis[1][0],
      y: center[1] + basis[1][1],
      kind: "basisY",
      plane,
    });
    const rangeRadius = Math.max(0.1, motion.face_fraction ?? 1) * 0.92;
    const minimumPoint = gaugePlanePoint(motion, motion.minimum_angle_degrees ?? -150, rangeRadius);
    const maximumPoint = gaugePlanePoint(motion, motion.maximum_angle_degrees ?? -30, rangeRadius);
    const middleAngle = ((motion.minimum_angle_degrees ?? -150) + (motion.maximum_angle_degrees ?? -30)) / 2;
    const lengthPoint = gaugePlanePoint(motion, middleAngle, motion.needle_length ?? 0.78);
    handles.push({ id: "gauge:minimum", x: minimumPoint[0], y: minimumPoint[1], kind: "gaugeMinimum" });
    handles.push({ id: "gauge:maximum", x: maximumPoint[0], y: maximumPoint[1], kind: "gaugeMaximum" });
    handles.push({ id: "gauge:length", x: lengthPoint[0], y: lengthPoint[1], kind: "gaugeLength" });
  } else if (motion.type === "mechanical_rotor" || motion.type === "mechanical_gear") {
    // Main face: an upright rectangle -- one handle moves it, one handle
    // resizes it (width/height together), no independent skew.
    const planes = getPlanes(motion);
    const mainPlane = planes[0];
    const mainCenter = getPlaneCenter(motion, mainPlane);
    const mainBasis = getPlaneBasis(motion, mainPlane);
    handles.push({ id: mainPlane.key + ":center", x: mainCenter[0], y: mainCenter[1], kind: "center", plane: mainPlane });
    handles.push({
      id: mainPlane.key + ":size",
      x: mainCenter[0] + mainBasis[0][0],
      y: mainCenter[1] + mainBasis[1][1],
      kind: "rectSize",
      plane: mainPlane,
    });

    // Hub / center plate: concentric with the main rectangle, same aspect
    // ratio -- a single handle only changes its size.
    const secondaryPlane = planes[1];
    if (secondaryPlane) {
      const mainExtent = planeExtent(mainBasis);
      const ratio = currentFillRatio(motion, secondaryPlane, mainPlane);
      handles.push({
        id: secondaryPlane.key + ":ratio",
        x: mainCenter[0] + mainExtent[0] * ratio,
        y: mainCenter[1] + mainExtent[1] * ratio,
        kind: "fillRatio",
        plane: secondaryPlane,
        mainPlane,
      });
    }

    if (motion.type === "mechanical_gear") {
      const depth = gearThicknessHandleVector(motion);
      handles.push({
        id: "gear:thickness",
        x: mainCenter[0] + depth[0],
        y: mainCenter[1] + depth[1],
        kind: "gearThickness",
      });
      if (motion.center_cap_bbox) {
        const mainExtent = planeExtent(mainBasis);
        const ratio = currentCapRatio(motion);
        handles.push({
          id: "gear:capRatio",
          x: mainCenter[0] + mainExtent[0] * ratio,
          y: mainCenter[1] + mainExtent[1] * ratio,
          kind: "gearCapRatio",
        });
      }
    }
  } else {
    const shape = getShapeSpec(motion);
    if (shape) {
      if (shape.kind === "polygon") {
        motion.polygon.forEach((point, index) => {
          handles.push({ id: "shape:vertex:" + index, x: point[0], y: point[1], kind: "vertex", index, field: "polygon" });
        });
        const cx = motion.polygon.reduce((sum, p) => sum + p[0], 0) / motion.polygon.length;
        const cy = motion.polygon.reduce((sum, p) => sum + p[1], 0) / motion.polygon.length;
        handles.push({ id: "shape:move", x: cx, y: cy, kind: "shapeMove", shapeKind: "polygon", field: "polygon" });
        if (motion.type === "vibration") {
          const pivot = motion.pivot || [cx, cy];
          const amplitude = motion.amplitude || [0.65, 1.0];
          // When pivot and selection center coincide, the center handle keeps
          // its more useful whole-selection drag behavior. Offset the pivot
          // numerically once and its own draggable handle appears.
          if (Math.hypot(pivot[0] - cx, pivot[1] - cy) > 0.2) {
            handles.push({ id: "vibration:pivot", x: pivot[0], y: pivot[1], kind: "vibrationPivot" });
          }
          handles.push({
            id: "vibration:amplitude",
            x: pivot[0] + amplitude[0],
            y: pivot[1] + amplitude[1],
            kind: "vibrationAmplitude",
          });
        } else if (motion.type === "vertical_gear") {
          const middle = motion.middle || [cx, cy];
          handles.push({ id: "vertical:middle", x: middle[0], y: middle[1], kind: "verticalMiddle" });
        }
      } else if (shape.kind === "bbox") {
        const [x0, y0, x1, y1] = motion.bbox;
        handles.push({ id: "shape:bboxMin", x: x0, y: y0, kind: "bboxMin" });
        handles.push({ id: "shape:bboxMax", x: x1, y: y1, kind: "bboxMax" });
        handles.push({ id: "shape:move", x: (x0 + x1) / 2, y: (y0 + y1) / 2, kind: "shapeMove", shapeKind: "bbox" });
        if (motion.type === "sweep" && (motion.axis === "circle" || motion.axis === "-circle")) {
          const center = motion.center || [(x0 + x1) / 2, (y0 + y1) / 2];
          const maxRadius = motion.max_radius ?? Math.hypot(x1 - x0, y1 - y0) / 2;
          handles.push({ id: "sweep:circleCenter", x: center[0], y: center[1], kind: "sweepCircleCenter" });
          handles.push({ id: "sweep:circleRadius", x: center[0] + maxRadius, y: center[1], kind: "sweepCircleRadius" });
        }
      } else if (shape.kind === "points") {
        motion.points.forEach((point, index) => {
          handles.push({ id: "shape:point:" + index, x: point[0], y: point[1], kind: "chasePoint", index });
        });
      } else if (shape.kind === "point") {
        const center = motion[shape.key];
        handles.push({ id: "shape:center", x: center[0], y: center[1], kind: "point", key: shape.key });
        if (shape.radiusKey) {
          const radius = motion[shape.radiusKey];
          handles.push({
            id: "shape:radiusX",
            x: center[0] + radius[0],
            y: center[1],
            kind: "radiusX",
            key: shape.key,
            radiusKey: shape.radiusKey,
          });
          handles.push({
            id: "shape:radiusY",
            x: center[0],
            y: center[1] + radius[1],
            kind: "radiusY",
            key: shape.key,
            radiusKey: shape.radiusKey,
          });
        }
      } else if (shape.kind === "ellipseRing") {
        const center = motion.center || [0, 0];
        const outer = motion.outer_radius || [1, 1];
        const inner = motion.inner_radius || [0.5, 0.5];
        handles.push({ id: "occluder:center", x: center[0], y: center[1], kind: "occluderCenter" });
        handles.push({
          id: "occluder:outerX",
          x: center[0] + outer[0],
          y: center[1],
          kind: "occluderOuterX",
        });
        handles.push({
          id: "occluder:outerY",
          x: center[0],
          y: center[1] + outer[1],
          kind: "occluderOuterY",
        });
        handles.push({
          id: "occluder:innerX",
          x: center[0] + inner[0],
          y: center[1],
          kind: "occluderInnerX",
        });
        handles.push({
          id: "occluder:innerY",
          x: center[0],
          y: center[1] + inner[1],
          kind: "occluderInnerY",
        });
        handles.push({
          id: "occluder:minY",
          x: center[0] - outer[0],
          y: motion.minimum_y ?? center[1] - outer[1],
          kind: "occluderMinY",
        });
        handles.push({
          id: "occluder:maxY",
          x: center[0] + outer[0],
          y: motion.maximum_y ?? center[1] + outer[1],
          kind: "occluderMaxY",
        });
      }
    }

    const maskKey = getMaskFieldKey(motion);
    if (maskKey && Array.isArray(motion[maskKey])) {
      const poly = motion[maskKey];
      poly.forEach((point, index) => {
        handles.push({ id: "mask:vertex:" + index, x: point[0], y: point[1], kind: "vertex", index, field: maskKey });
      });
      const cx = poly.reduce((sum, p) => sum + p[0], 0) / poly.length;
      const cy = poly.reduce((sum, p) => sum + p[1], 0) / poly.length;
      handles.push({ id: "mask:move", x: cx, y: cy, kind: "shapeMove", shapeKind: "polygon", field: maskKey });
    }
  }
  state.handles = handles;
  return handles;
}

const PRIMARY_HANDLE_KINDS = new Set([
  "center",
  "vertex",
  "chasePoint",
  "point",
  "bboxMin",
  "bboxMax",
  "vibrationPivot",
  "verticalMiddle",
  "occluderCenter",
  "occluderMinY",
  "occluderMaxY",
  "sweepCircleCenter",
  "gaugeMinimum",
  "gaugeMaximum",
  "gearThickness",
  "rectSize",
]);

function drawCrosshair(cx, cy, color) {
  ctx.strokeStyle = color;
  ctx.beginPath();
  ctx.moveTo(cx - 7, cy);
  ctx.lineTo(cx + 7, cy);
  ctx.moveTo(cx, cy - 7);
  ctx.lineTo(cx, cy + 7);
  ctx.stroke();
}

function drawGaugeRangeOverlay(motion, scale) {
  const minimum = motion.minimum_angle_degrees ?? -150;
  const maximum = motion.maximum_angle_degrees ?? -30;
  const radius = Math.max(0.1, motion.face_fraction ?? 1) * 0.92;
  ctx.strokeStyle = "#ef6d87";
  ctx.beginPath();
  const steps = Math.max(12, Math.ceil(Math.abs(maximum - minimum) / 5));
  for (let index = 0; index <= steps; index++) {
    const angle = minimum + (maximum - minimum) * index / steps;
    const point = gaugePlanePoint(motion, angle, radius);
    if (index === 0) ctx.moveTo(point[0] * scale, point[1] * scale);
    else ctx.lineTo(point[0] * scale, point[1] * scale);
  }
  ctx.stroke();
  const center = motion.center || [0, 0];
  for (const angle of [minimum, maximum]) {
    const point = gaugePlanePoint(motion, angle, radius);
    ctx.beginPath();
    ctx.moveTo(center[0] * scale, center[1] * scale);
    ctx.lineTo(point[0] * scale, point[1] * scale);
    ctx.stroke();
  }
}

function drawOverlay() {
  const scale = worldScale();
  const handles = computeHandles();
  const motion = state.motion;
  ctx.save();
  ctx.lineWidth = 1.5;

  if (motion.type === "gauge") {
    const plane = getPlanes(motion)[0];
    const center = getPlaneCenter(motion, plane);
    const cx = center[0] * scale;
    const cy = center[1] * scale;
    const basis = getPlaneBasis(motion, plane);
    drawArrow(cx, cy, (center[0] + basis[0][0]) * scale, (center[1] + basis[0][1]) * scale, "#e05d5d");
    drawArrow(cx, cy, (center[0] + basis[1][0]) * scale, (center[1] + basis[1][1]) * scale, "#5dc26a");
    drawCrosshair(cx, cy, plane.color);
    drawGaugeRangeOverlay(motion, scale);
  } else if (motion.type === "mechanical_rotor" || motion.type === "mechanical_gear") {
    const planes = getPlanes(motion);
    const mainPlane = planes[0];
    const mainCenter = getPlaneCenter(motion, mainPlane);
    const mainBasis = getPlaneBasis(motion, mainPlane);
    ctx.strokeStyle = mainPlane.color;
    ctx.strokeRect(
      (mainCenter[0] - mainBasis[0][0]) * scale,
      (mainCenter[1] - mainBasis[1][1]) * scale,
      mainBasis[0][0] * 2 * scale,
      mainBasis[1][1] * 2 * scale
    );
    drawCrosshair(mainCenter[0] * scale, mainCenter[1] * scale, mainPlane.color);

    const secondaryPlane = planes[1];
    if (secondaryPlane) {
      const mainExtent = planeExtent(mainBasis);
      const ratio = currentFillRatio(motion, secondaryPlane, mainPlane);
      const rx = mainExtent[0] * ratio;
      const ry = mainExtent[1] * ratio;
      ctx.strokeStyle = secondaryPlane.color;
      ctx.setLineDash([4, 3]);
      ctx.strokeRect(
        (mainCenter[0] - rx) * scale,
        (mainCenter[1] - ry) * scale,
        rx * 2 * scale,
        ry * 2 * scale
      );
      ctx.setLineDash([]);
    }

    if (motion.type === "mechanical_gear") {
      const depth = gearThicknessHandleVector(motion);
      const actualLength = Math.hypot(...gearThicknessVector(motion));
      ctx.setLineDash(actualLength < 0.75 ? [4, 3] : []);
      drawArrow(
        mainCenter[0] * scale,
        mainCenter[1] * scale,
        (mainCenter[0] + depth[0]) * scale,
        (mainCenter[1] + depth[1]) * scale,
        "#6fc5e8"
      );
      ctx.setLineDash([]);

      if (motion.center_cap_bbox) {
        const mainExtent = planeExtent(mainBasis);
        const ratio = currentCapRatio(motion);
        const rx = mainExtent[0] * ratio;
        const ry = mainExtent[1] * ratio;
        ctx.strokeStyle = "#b0d96f";
        ctx.setLineDash([4, 3]);
        ctx.strokeRect(
          (mainCenter[0] - rx) * scale,
          (mainCenter[1] - ry) * scale,
          rx * 2 * scale,
          ry * 2 * scale
        );
        ctx.setLineDash([]);
      }
    }
  } else {
    const shape = getShapeSpec(motion);
    if (shape) {
      ctx.strokeStyle = motion.type === "source_occluder" ? "#ef6d87" : "#d9a34a";
      if (shape.kind === "polygon") {
        ctx.beginPath();
        motion.polygon.forEach((point, index) => {
          const sx = point[0] * scale;
          const sy = point[1] * scale;
          if (index === 0) ctx.moveTo(sx, sy);
          else ctx.lineTo(sx, sy);
        });
        ctx.closePath();
        ctx.stroke();
      } else if (shape.kind === "bbox") {
        const [x0, y0, x1, y1] = motion.bbox;
        ctx.strokeRect(x0 * scale, y0 * scale, (x1 - x0) * scale, (y1 - y0) * scale);
        if (motion.type === "sweep" && (motion.axis === "circle" || motion.axis === "-circle")) {
          const center = motion.center || [(x0 + x1) / 2, (y0 + y1) / 2];
          const maxRadius = motion.max_radius ?? Math.hypot(x1 - x0, y1 - y0) / 2;
          const minRadius = motion.min_radius ?? 0;
          ctx.setLineDash([4, 3]);
          for (const r of [minRadius, maxRadius]) {
            if (r <= 0) continue;
            ctx.beginPath();
            ctx.ellipse(center[0] * scale, center[1] * scale, r * scale, r * scale, 0, 0, Math.PI * 2);
            ctx.stroke();
          }
          ctx.setLineDash([]);
          drawCrosshair(center[0] * scale, center[1] * scale, "#d9a34a");
        }
      } else if (shape.kind === "point") {
        const center = motion[shape.key];
        drawCrosshair(center[0] * scale, center[1] * scale, "#d9a34a");
        if (shape.radiusKey) {
          const radius = motion[shape.radiusKey];
          ctx.beginPath();
          ctx.ellipse(
            center[0] * scale,
            center[1] * scale,
            Math.abs(radius[0]) * scale,
            Math.abs(radius[1]) * scale,
            0,
            0,
            Math.PI * 2
          );
          ctx.stroke();
        }
      } else if (shape.kind === "ellipseRing") {
        const center = motion.center || [0, 0];
        const outer = motion.outer_radius || [1, 1];
        const inner = motion.inner_radius || [0.5, 0.5];
        for (const radius of [outer, inner]) {
          ctx.beginPath();
          ctx.ellipse(
            center[0] * scale,
            center[1] * scale,
            Math.abs(radius[0]) * scale,
            Math.abs(radius[1]) * scale,
            0,
            0,
            Math.PI * 2
          );
          ctx.stroke();
        }
        ctx.setLineDash([5, 4]);
        for (const y of [
          motion.minimum_y ?? center[1] - outer[1],
          motion.maximum_y ?? center[1] + outer[1],
        ]) {
          ctx.beginPath();
          ctx.moveTo((center[0] - outer[0]) * scale, y * scale);
          ctx.lineTo((center[0] + outer[0]) * scale, y * scale);
          ctx.stroke();
        }
        ctx.setLineDash([]);
      }
    }

    const maskKey = getMaskFieldKey(motion);
    if (maskKey && Array.isArray(motion[maskKey])) {
      ctx.strokeStyle = "#b06fd9";
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      motion[maskKey].forEach((point, index) => {
        const sx = point[0] * scale;
        const sy = point[1] * scale;
        if (index === 0) ctx.moveTo(sx, sy);
        else ctx.lineTo(sx, sy);
      });
      ctx.closePath();
      ctx.stroke();
      ctx.setLineDash([]);
    }
    if (motion.type === "vibration") {
      const pivot = motion.pivot || [
        motion.polygon.reduce((sum, point) => sum + point[0], 0) / motion.polygon.length,
        motion.polygon.reduce((sum, point) => sum + point[1], 0) / motion.polygon.length,
      ];
      const amplitude = motion.amplitude || [0.65, 1.0];
      drawArrow(
        pivot[0] * scale,
        pivot[1] * scale,
        (pivot[0] + amplitude[0]) * scale,
        (pivot[1] + amplitude[1]) * scale,
        "#6fb4d9"
      );
      drawCrosshair(pivot[0] * scale, pivot[1] * scale, "#6fb4d9");
    } else if (motion.type === "vertical_gear") {
      const middle = motion.middle || [
        motion.polygon.reduce((sum, point) => sum + point[0], 0) / motion.polygon.length,
        motion.polygon.reduce((sum, point) => sum + point[1], 0) / motion.polygon.length,
      ];
      const topWidth = [
        motion.polygon[1][0] - motion.polygon[0][0],
        motion.polygon[1][1] - motion.polygon[0][1],
      ];
      const bottomWidth = [
        motion.polygon[2][0] - motion.polygon[3][0],
        motion.polygon[2][1] - motion.polygon[3][1],
      ];
      const across = [(topWidth[0] + bottomWidth[0]) / 2, (topWidth[1] + bottomWidth[1]) / 2];
      ctx.strokeStyle = "#6fb4d9";
      ctx.beginPath();
      ctx.moveTo((middle[0] - across[0] * 0.55) * scale, (middle[1] - across[1] * 0.55) * scale);
      ctx.lineTo((middle[0] + across[0] * 0.55) * scale, (middle[1] + across[1] * 0.55) * scale);
      ctx.stroke();
      drawCrosshair(middle[0] * scale, middle[1] * scale, "#6fb4d9");
    }
  }

  for (const handle of handles) {
    const hx = handle.x * scale;
    const hy = handle.y * scale;
    const selected = handle.id === state.selectedHandleId;
    ctx.beginPath();
    ctx.arc(hx, hy, selected ? 6 : 4.5, 0, Math.PI * 2);
    ctx.fillStyle = selected ? "#ffd479" : PRIMARY_HANDLE_KINDS.has(handle.kind) ? "#ffffff" : "#1b1c1e";
    ctx.fill();
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = "#000000aa";
    ctx.stroke();
  }
  ctx.restore();
}

function drawArrow(x0, y0, x1, y1, color) {
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(x0, y0);
  ctx.lineTo(x1, y1);
  ctx.stroke();
  const angle = Math.atan2(y1 - y0, x1 - x0);
  const size = 6;
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x1 - size * Math.cos(angle - 0.4), y1 - size * Math.sin(angle - 0.4));
  ctx.lineTo(x1 - size * Math.cos(angle + 0.4), y1 - size * Math.sin(angle + 0.4));
  ctx.closePath();
  ctx.fill();
}

function drawFrame(timestamp) {
  const scale = worldScale();
  const asset = state.asset;
  ctx.imageSmoothingEnabled = smoothingToggle.checked;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (asset && state.frameImages.length > 0) {
    const index = state.playing
      ? Math.floor(timestamp / frameIntervalMs()) % state.frameImages.length
      : state.pausedIndex % state.frameImages.length;
    const image = state.frameImages[index];
    ctx.drawImage(image, 0, 0, asset.size[0] * scale, asset.size[1] * scale);
  }
  if (overlayToggle.checked && state.motion) drawOverlay();
  requestAnimationFrame(drawFrame);
}
requestAnimationFrame(drawFrame);

// ------------------------------------------------------------- interaction

function screenToWorld(event) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: ((event.clientX - rect.left) * (canvas.width / rect.width)) / worldScale(),
    y: ((event.clientY - rect.top) * (canvas.height / rect.height)) / worldScale(),
  };
}

function nearestHandle(worldX, worldY) {
  const scale = worldScale();
  const thresholdWorld = HANDLE_HIT_PX / scale;
  let best = null;
  let bestDist = thresholdWorld;
  for (const handle of state.handles) {
    const dist = Math.hypot(handle.x - worldX, handle.y - worldY);
    if (dist <= bestDist) {
      best = handle;
      bestDist = dist;
    }
  }
  return best;
}

function applyHandleMove(handle, x, y) {
  x = round2(x);
  y = round2(y);
  const motion = state.motion;

  switch (handle.kind) {
    case "center": {
      setPlaneCenter(motion, handle.plane, [x, y]);
      break;
    }
    case "basisX":
    case "basisY": {
      const center = getPlaneCenter(motion, handle.plane);
      const vec = [round2(x - center[0]), round2(y - center[1])];
      if (!motion[handle.plane.basisKey]) motion[handle.plane.basisKey] = [
        [10, 0],
        [0, 10],
      ];
      motion[handle.plane.basisKey][handle.kind === "basisX" ? 0 : 1] = vec;
      break;
    }
    case "rectSize": {
      const center = getPlaneCenter(motion, handle.plane);
      motion[handle.plane.basisKey] = [
        [Math.max(1, round2(x - center[0])), 0],
        [0, Math.max(1, round2(y - center[1]))],
      ];
      break;
    }
    case "fillRatio": {
      const mainExtent = planeExtent(getPlaneBasis(motion, handle.mainPlane));
      const mainCenter = getPlaneCenter(motion, handle.mainPlane);
      const ratioX = mainExtent[0] > 0.0001 ? (x - mainCenter[0]) / mainExtent[0] : 0.4;
      const ratioY = mainExtent[1] > 0.0001 ? (y - mainCenter[1]) / mainExtent[1] : 0.4;
      applyFillRatio(motion, handle.plane, handle.mainPlane, (ratioX + ratioY) / 2);
      break;
    }
    case "gearCapRatio": {
      const mainExtent = planeExtent(motion.plane_basis || [[10, 0], [0, 10]]);
      const [cx, cy] = motion.center;
      const ratioX = mainExtent[0] > 0.0001 ? (x - cx) / mainExtent[0] : 0.3;
      const ratioY = mainExtent[1] > 0.0001 ? (y - cy) / mainExtent[1] : 0.3;
      applyCapRatio(motion, (ratioX + ratioY) / 2);
      break;
    }
    case "vertex": {
      motion[handle.field][handle.index] = [x, y];
      break;
    }
    case "chasePoint": {
      motion.points[handle.index][0] = x;
      motion.points[handle.index][1] = y;
      break;
    }
    case "point": {
      motion[handle.key] = [x, y];
      break;
    }
    case "occluderCenter": {
      const previous = motion.center || [0, 0];
      const dy = y - previous[1];
      motion.center = [x, y];
      if (motion.minimum_y !== undefined) motion.minimum_y = round2(motion.minimum_y + dy);
      if (motion.maximum_y !== undefined) motion.maximum_y = round2(motion.maximum_y + dy);
      break;
    }
    case "occluderOuterX": {
      motion.outer_radius[0] = Math.max(0.5, round2(Math.abs(x - motion.center[0])));
      motion.inner_radius[0] = Math.min(motion.inner_radius[0], Math.max(0.1, motion.outer_radius[0] - 0.1));
      break;
    }
    case "occluderOuterY": {
      motion.outer_radius[1] = Math.max(0.5, round2(Math.abs(y - motion.center[1])));
      motion.inner_radius[1] = Math.min(motion.inner_radius[1], Math.max(0.1, motion.outer_radius[1] - 0.1));
      break;
    }
    case "occluderInnerX": {
      motion.inner_radius[0] = clamp(round2(Math.abs(x - motion.center[0])), 0.1, Math.max(0.1, motion.outer_radius[0] - 0.1));
      break;
    }
    case "occluderInnerY": {
      motion.inner_radius[1] = clamp(round2(Math.abs(y - motion.center[1])), 0.1, Math.max(0.1, motion.outer_radius[1] - 0.1));
      break;
    }
    case "occluderMinY": {
      motion.minimum_y = Math.min(y, motion.maximum_y ?? y);
      break;
    }
    case "occluderMaxY": {
      motion.maximum_y = Math.max(y, motion.minimum_y ?? y);
      break;
    }
    case "gaugeMinimum":
    case "gaugeMaximum": {
      const local = gaugeLocalPoint(motion, x, y);
      let angle = Math.atan2(local[1], local[0]) * 180 / Math.PI;
      const key = handle.kind === "gaugeMinimum" ? "minimum_angle_degrees" : "maximum_angle_degrees";
      const current = motion[key] ?? (handle.kind === "gaugeMinimum" ? -150 : -30);
      while (angle - current > 180) angle -= 360;
      while (angle - current < -180) angle += 360;
      motion[key] = round2(angle);
      break;
    }
    case "gaugeLength": {
      const local = gaugeLocalPoint(motion, x, y);
      motion.needle_length = clamp(round2(Math.hypot(local[0], local[1])), 0.05, 1.2);
      break;
    }
    case "gearThickness": {
      const center = motion.center || [0, 0];
      setGearThicknessVector(motion, [x - center[0], y - center[1]]);
      break;
    }
    case "vibrationPivot": {
      motion.pivot = [x, y];
      break;
    }
    case "vibrationAmplitude": {
      const pivot = motion.pivot || [0, 0];
      motion.amplitude = [round2(x - pivot[0]), round2(y - pivot[1])];
      break;
    }
    case "verticalMiddle": {
      motion.middle = [x, y];
      break;
    }
    case "radiusX": {
      const center = motion[handle.key];
      const current = motion[handle.radiusKey] || [1, 1];
      motion[handle.radiusKey] = [round2(x - center[0]) || 0.1, current[1]];
      break;
    }
    case "radiusY": {
      const center = motion[handle.key];
      const current = motion[handle.radiusKey] || [1, 1];
      motion[handle.radiusKey] = [current[0], round2(y - center[1]) || 0.1];
      break;
    }
    case "sweepCircleCenter": {
      motion.center = [x, y];
      break;
    }
    case "sweepCircleRadius": {
      const [x0, y0, x1, y1] = motion.bbox;
      const center = motion.center || [(x0 + x1) / 2, (y0 + y1) / 2];
      motion.max_radius = Math.max(0.5, round2(Math.hypot(x - center[0], y - center[1])));
      break;
    }
    case "bboxMin": {
      motion.bbox[0] = x;
      motion.bbox[1] = y;
      normalizeBbox(motion);
      break;
    }
    case "bboxMax": {
      motion.bbox[2] = x;
      motion.bbox[3] = y;
      normalizeBbox(motion);
      break;
    }
    case "shapeMove": {
      const origin = state.dragOrigin;
      const dx = x - origin.startX;
      const dy = y - origin.startY;
      if (handle.shapeKind === "polygon") {
        motion[handle.field] = origin.snapshot.map((point) => [round2(point[0] + dx), round2(point[1] + dy)]);
        if (motion.type === "vibration" && handle.field === "polygon" && origin.pivotSnapshot) {
          motion.pivot = [round2(origin.pivotSnapshot[0] + dx), round2(origin.pivotSnapshot[1] + dy)];
        }
        if (motion.type === "vertical_gear" && handle.field === "polygon" && origin.middleSnapshot) {
          motion.middle = [round2(origin.middleSnapshot[0] + dx), round2(origin.middleSnapshot[1] + dy)];
        }
      } else if (handle.shapeKind === "bbox") {
        motion.bbox = [
          round2(origin.snapshot[0] + dx),
          round2(origin.snapshot[1] + dy),
          round2(origin.snapshot[2] + dx),
          round2(origin.snapshot[3] + dy),
        ];
      }
      break;
    }
  }
}

canvas.addEventListener("mousedown", (event) => {
  computeHandles();
  const { x, y } = screenToWorld(event);
  const handle = nearestHandle(x, y);
  state.selectedHandleId = handle ? handle.id : null;
  if (handle) {
    state.dragging = handle;
    if (handle.kind === "shapeMove") {
      state.dragOrigin = {
        startX: round2(x),
        startY: round2(y),
        snapshot: JSON.parse(JSON.stringify(handle.shapeKind === "polygon" ? state.motion[handle.field] : state.motion.bbox)),
        pivotSnapshot:
          state.motion.type === "vibration" && Array.isArray(state.motion.pivot)
            ? JSON.parse(JSON.stringify(state.motion.pivot))
            : null,
        middleSnapshot:
          state.motion.type === "vertical_gear" && Array.isArray(state.motion.middle)
            ? JSON.parse(JSON.stringify(state.motion.middle))
            : null,
      };
    }
    canvas.style.cursor = "grabbing";
  }
});

window.addEventListener("mousemove", (event) => {
  if (!state.dragging) {
    if (state.motion) {
      const { x, y } = screenToWorld(event);
      canvas.style.cursor = nearestHandle(x, y) ? "grab" : "crosshair";
    }
    return;
  }
  const { x, y } = screenToWorld(event);
  applyHandleMove(state.dragging, x, y);
  refreshGeometryInputs();
  onMotionChanged();
});

window.addEventListener("mouseup", () => {
  if (state.dragging) {
    state.dragging = null;
    canvas.style.cursor = "crosshair";
    scheduleRender(true);
  }
});

document.addEventListener("keydown", (event) => {
  if (!state.selectedHandleId) return;
  const arrowKeys = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
  const delta = arrowKeys[event.key];
  if (!delta) return;
  if (document.activeElement && document.activeElement.tagName === "TEXTAREA") return;
  event.preventDefault();
  const handle = state.handles.find((h) => h.id === state.selectedHandleId);
  if (!handle) return;
  const step = event.shiftKey ? 0.1 : 1;
  const dx = delta[0] * step;
  const dy = delta[1] * step;
  if (handle.kind === "shapeMove") {
    // No mousedown snapshot exists for a pure keyboard nudge; shift the shape directly.
    if (handle.shapeKind === "polygon") {
      state.motion[handle.field] = state.motion[handle.field].map((p) => [round2(p[0] + dx), round2(p[1] + dy)]);
    } else if (handle.shapeKind === "bbox") {
      state.motion.bbox = state.motion.bbox.map((v, i) => round2(v + (i % 2 === 0 ? dx : dy)));
    }
  } else {
    applyHandleMove(handle, handle.x + dx, handle.y + dy);
  }
  refreshGeometryInputs();
  onMotionChanged();
});

// ------------------------------------------------------------------ panels

function clearChildren(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function row(label) {
  const wrap = document.createElement("div");
  wrap.className = "row";
  const labelEl = document.createElement("label");
  labelEl.textContent = label;
  wrap.appendChild(labelEl);
  return wrap;
}

function numberInput(value, onChange, step) {
  const input = document.createElement("input");
  input.type = "number";
  input.step = step || "0.1";
  input.value = value;
  input.addEventListener("input", () => {
    const parsed = parseFloat(input.value);
    if (!Number.isNaN(parsed)) onChange(parsed);
  });
  return input;
}

function vecRow(label, getVec, setVec) {
  const wrap = row(label);
  const container = document.createElement("div");
  container.className = "vec2";
  const vec = getVec();
  const xInput = numberInput(vec[0], (value) => {
    const current = getVec();
    setVec([round2(value), current[1]]);
    refreshGeometryInputs();
    onMotionChanged();
  });
  const yInput = numberInput(vec[1], (value) => {
    const current = getVec();
    setVec([current[0], round2(value)]);
    refreshGeometryInputs();
    onMotionChanged();
  });
  container.appendChild(xInput);
  container.appendChild(yInput);
  wrap.appendChild(container);
  wrap._refresh = () => {
    const v = getVec();
    if (document.activeElement !== xInput) xInput.value = v[0];
    if (document.activeElement !== yInput) yInput.value = v[1];
  };
  state.refreshCallbacks.push(wrap._refresh);
  return wrap;
}

function decimalsForStep(step) {
  const text = String(step);
  const dot = text.indexOf(".");
  return dot === -1 ? 0 : text.length - dot - 1;
}

function sliderRow(label, value, min, max, step, onChange) {
  const wrap = row(label);
  const decimals = decimalsForStep(step);
  const input = document.createElement("input");
  input.type = "range";
  input.min = min;
  input.max = max;
  input.step = step;
  input.value = value;
  const valueLabel = document.createElement("span");
  valueLabel.className = "value";
  valueLabel.textContent = Number(value).toFixed(decimals);
  input.addEventListener("input", () => {
    valueLabel.textContent = Number(input.value).toFixed(decimals);
    onChange(parseFloat(input.value));
    onMotionChanged();
  });
  wrap.appendChild(input);
  wrap.appendChild(valueLabel);
  return wrap;
}

function buildGearCenterFillSection(container, motion) {
  const heading = document.createElement("h2");
  heading.textContent = "Center fill";
  container.appendChild(heading);

  const mode = motion.center_cap_bbox ? "painted" : motion.source_center_basis ? "source" : "none";

  const modeRow = row("Mode");
  const select = document.createElement("select");
  for (const [value, label] of [
    ["none", "None (shows whatever's underneath)"],
    ["source", "Reveal source art"],
    ["painted", "Painted disc"],
  ]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    if (value === mode) option.selected = true;
    select.appendChild(option);
  }
  select.addEventListener("change", () => {
    const next = select.value;
    delete motion.center_cap_bbox;
    delete motion.center_cap_color;
    delete motion.source_center_basis;
    delete motion.source_center;
    const basis = motion.plane_basis || [
      [14, 0],
      [0, 14],
    ];
    const [cx, cy] = motion.center;
    if (next === "source") {
      motion.source_center = [cx, cy];
      motion.source_center_basis = [
        [round2(basis[0][0] * 0.45), round2(basis[0][1] * 0.45)],
        [round2(basis[1][0] * 0.45), round2(basis[1][1] * 0.45)],
      ];
      motion.center_feather = motion.center_feather ?? 0.65;
    } else if (next === "painted") {
      const r = Math.max(4, round2(Math.min(Math.abs(basis[0][0]), Math.abs(basis[1][1])) * 0.5));
      motion.center_cap_bbox = [round2(cx - r), round2(cy - r), round2(cx + r), round2(cy + r)];
      motion.center_cap_color = motion.center_cap_color || motion.gear_color || [112, 88, 51];
    }
    buildPanels();
    onMotionChanged(true);
  });
  modeRow.appendChild(select);
  container.appendChild(modeRow);

  if (mode === "none") {
    const note = document.createElement("p");
    note.className = "muted-note";
    note.textContent =
      "The center currently shows whatever's underneath -- usually the untouched source sprite, " +
      "which reads as an empty hole if nothing was drawn there. Pick a mode above to control it.";
    container.appendChild(note);
    return;
  }

  if (mode === "source") {
    const [mainPlane, sourceCenterPlane] = getPlanes(motion);
    fillRatioSection(container, motion, sourceCenterPlane, mainPlane, { featherKey: "center_feather" });
    const note = document.createElement("p");
    note.className = "muted-note";
    note.textContent =
      "Shows the sprite's own original pixels inside this ellipse -- if nothing is drawn there in the " +
      "source art, it will still look empty. Use \"Painted disc\" for a guaranteed fill instead.";
    container.appendChild(note);
  } else if (mode === "painted") {
    container.appendChild(
      sliderRow("Size (% of gear)", currentCapRatio(motion) * 100, 5, 95, 1, (percent) => {
        applyCapRatio(motion, percent / 100);
      })
    );
    container.appendChild(
      colorRow(
        "Color",
        () => motion.center_cap_color || motion.gear_color || [112, 88, 51],
        (rgb) => {
          motion.center_cap_color = rgb;
        }
      )
    );
    const note = document.createElement("p");
    note.className = "muted-note";
    note.textContent = "Always centered on the gear and scaled to its aspect ratio -- only the size is adjustable.";
    container.appendChild(note);
  }
}

function buildMechanicalGearConstructionSection(container, motion) {
  const heading = document.createElement("h2");
  heading.textContent = "Face-cog construction";
  container.appendChild(heading);

  const lengthRow = row("Depth length (px)");
  const lengthInput = numberInput(round2(Math.hypot(...gearThicknessVector(motion))), (value) => {
    const current = gearThicknessVector(motion);
    const currentLength = Math.hypot(current[0], current[1]);
    const direction = currentLength > 0.000001
      ? [current[0] / currentLength, current[1] / currentLength]
      : (motion.thickness_direction || [0.55, 0.83]);
    const directionLength = Math.max(0.000001, Math.hypot(direction[0], direction[1]));
    setGearThicknessVector(motion, [
      direction[0] / directionLength * Math.max(0, value),
      direction[1] / directionLength * Math.max(0, value),
    ]);
    refreshGeometryInputs();
    onMotionChanged();
  }, "0.1");
  lengthInput.min = "0";
  lengthRow.appendChild(lengthInput);
  lengthRow._refresh = () => {
    if (document.activeElement !== lengthInput) {
      lengthInput.value = round2(Math.hypot(...gearThicknessVector(motion)));
    }
  };
  state.refreshCallbacks.push(lengthRow._refresh);
  container.appendChild(lengthRow);

  container.appendChild(
    vecRow(
      "Projected depth (x, y)",
      () => gearThicknessVector(motion).map(round2),
      (vector) => setGearThicknessVector(motion, vector)
    )
  );

  const styleRow = row("Body filling");
  const styleSelect = document.createElement("select");
  for (const [value, label] of [
    ["open", "Open (ring only)"],
    ["solid", "Solid"],
    ["bars", "Bars / spokes"],
    ["solid_with_holes", "Solid with holes"],
  ]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    if (value === (motion.fill_style ?? "open")) option.selected = true;
    styleSelect.appendChild(option);
  }
  styleSelect.addEventListener("change", () => {
    motion.fill_style = styleSelect.value;
    if (motion.fill_count == null) motion.fill_count = Math.max(3, Math.round((motion.tooth_count ?? 10) / 2));
    buildPanels();
    onMotionChanged(true);
  });
  styleRow.appendChild(styleSelect);
  container.appendChild(styleRow);

  const style = motion.fill_style ?? "open";
  if (style === "bars" || style === "solid_with_holes") {
    const countRow = row(style === "bars" ? "Spoke count" : "Hole count");
    countRow.appendChild(
      numberInput(motion.fill_count ?? Math.max(3, Math.round((motion.tooth_count ?? 10) / 2)), (value) => {
        motion.fill_count = Math.max(2, Math.round(value));
        onMotionChanged();
      }, "1")
    );
    container.appendChild(countRow);
  }
  if (style === "bars") {
    container.appendChild(
      sliderRow("Spoke width (%)", (motion.fill_width_fraction ?? 0.24) * 100, 4, 80, 1, (value) => {
        motion.fill_width_fraction = round2(value / 100);
      })
    );
  } else if (style === "solid_with_holes") {
    container.appendChild(
      sliderRow("Hole size (%)", (motion.hole_radius_fraction ?? 0.12) * 100, 3, 28, 1, (value) => {
        motion.hole_radius_fraction = round2(value / 100);
      })
    );
  }

  const note = document.createElement("p");
  note.className = "muted-note";
  note.textContent =
    "Drag the blue depth handle from the cog center: direction sets the projected extrusion angle and distance sets its length. " +
    "Thickness is a displaced rear gear face, so tooth and opening sidewalls inherit the same perspective. " +
    "Spokes and holes rotate rigidly with the teeth; loop speed automatically respects their shared symmetry.";
  container.appendChild(note);
}

// gear_color drives every generated cog pixel (teeth, body fill, thickness
// shading) but had no direct control -- only center_cap_color ever referenced
// it, as a fallback. gear_edge/gear_root_edge/gear_inner_edge are the
// silhouette/root-circle/inner-cut outline colors baked into generate_animations.py
// as RGBA 4-tuples, so each gets its own color swatch plus an opacity slider
// for the alpha channel instead of losing it to a plain 3-channel colorRow.
function buildGearColorSection(container, motion) {
  const heading = document.createElement("h2");
  heading.textContent = "Cog color";
  container.appendChild(heading);

  container.appendChild(
    colorRow("Body / tooth color", () => motion.gear_color || [112, 88, 51], (rgb) => {
      motion.gear_color = rgb;
    })
  );
  container.appendChild(
    sliderRow("Extruded side shading (brightness)", motion.thickness_brightness ?? 0.46, 0.08, 1, 0.01, (value) => {
      motion.thickness_brightness = value;
    })
  );
  container.appendChild(
    sliderRow("Extruded side edge highlight", motion.thickness_edge_highlight ?? 0.14, 0, 0.8, 0.01, (value) => {
      motion.thickness_edge_highlight = value;
    })
  );

  const edgeColors = [
    ["Tooth-tip edge", "gear_edge", [175, 133, 67, 170]],
    ["Root circle edge", "gear_root_edge", [56, 43, 28, 165]],
    ["Inner cut edge", "gear_inner_edge", [43, 34, 24, 230]],
  ];
  for (const [label, key, fallback] of edgeColors) {
    container.appendChild(
      colorRow(label, () => (motion[key] || fallback).slice(0, 3), (rgb) => {
        const alpha = (motion[key] || fallback)[3];
        motion[key] = [...rgb, alpha];
      })
    );
    container.appendChild(
      sliderRow(`${label} opacity`, (motion[key] || fallback)[3], 0, 255, 1, (value) => {
        const current = motion[key] || fallback;
        motion[key] = [current[0], current[1], current[2], Math.round(value)];
      })
    );
  }

  const note = document.createElement("p");
  note.className = "muted-note";
  note.textContent =
    "Body/tooth color also tints any revealed source material (see Face-cog construction). " +
    "Edge colors trace the tooth silhouette, root circle, and inner cut lines (spokes/holes) respectively.";
  container.appendChild(note);
}

function planeSection(container, motion, plane) {
  const heading = document.createElement("h3");
  heading.textContent = plane.label;
  container.appendChild(heading);
  container.appendChild(
    vecRow(
      "Position (x, y)",
      () => getPlaneCenter(motion, plane),
      (v) => setPlaneCenter(motion, plane, v)
    )
  );
  if (plane.basisKey) {
    container.appendChild(
      vecRow(
        "Scale/skew X",
        () => getPlaneBasis(motion, plane)[0],
        (v) => {
          if (!motion[plane.basisKey]) motion[plane.basisKey] = [
            [10, 0],
            [0, 10],
          ];
          motion[plane.basisKey][0] = v;
        }
      )
    );
    container.appendChild(
      vecRow(
        "Scale/skew Y",
        () => getPlaneBasis(motion, plane)[1],
        (v) => {
          if (!motion[plane.basisKey]) motion[plane.basisKey] = [
            [10, 0],
            [0, 10],
          ];
          motion[plane.basisKey][1] = v;
        }
      )
    );
  }
}

// Cog/fan main face: an upright rectangle, no independent skew per axis --
// position plus a single width/height pair.
function mechanicalPlaneSection(container, motion, plane) {
  const heading = document.createElement("h3");
  heading.textContent = plane.label;
  container.appendChild(heading);
  container.appendChild(
    vecRow(
      "Position (x, y)",
      () => getPlaneCenter(motion, plane),
      (v) => setPlaneCenter(motion, plane, v)
    )
  );
  container.appendChild(
    vecRow(
      "Size (width, height)",
      () => planeExtent(getPlaneBasis(motion, plane)).map(round2),
      (v) => {
        motion[plane.basisKey] = [
          [Math.max(1, round2(v[0])), 0],
          [0, Math.max(1, round2(v[1]))],
        ];
      }
    )
  );
  const note = document.createElement("p");
  note.className = "muted-note";
  note.textContent =
    "Always an upright rectangle centered on Position -- no tilt. For the rare asset that truly needs " +
    "perspective skew, edit plane_basis directly in the raw JSON panel below.";
  container.appendChild(note);
}

// Anything concentric with a cog/fan (a fan's hub, a gear's center plate):
// locked to the main plane's center and aspect ratio, so there's only one
// number to get right instead of a whole second position+basis pair.
function fillRatioSection(container, motion, plane, mainPlane, options) {
  const heading = document.createElement("h3");
  heading.textContent = `${plane.label} (centered, scaled to ${mainPlane.label.toLowerCase()})`;
  container.appendChild(heading);
  container.appendChild(
    sliderRow(
      `Size (% of ${mainPlane.label.toLowerCase()})`,
      currentFillRatio(motion, plane, mainPlane) * 100,
      5,
      95,
      1,
      (percent) => {
        applyFillRatio(motion, plane, mainPlane, percent / 100);
      }
    )
  );
  if (options && options.featherKey) {
    container.appendChild(
      sliderRow(`Feather`, motion[options.featherKey] ?? 0.6, 0, 1.5, 0.01, (v) => {
        motion[options.featherKey] = v;
      })
    );
  }
  const note = document.createElement("p");
  note.className = "muted-note";
  note.textContent = `${plane.label} always stays centered on the ${mainPlane.label.toLowerCase()} and keeps its aspect ratio -- only the size is adjustable.`;
  container.appendChild(note);
}

function addMaskVertex() {
  const key = getMaskFieldKey(state.motion);
  const poly = key && state.motion[key];
  if (!Array.isArray(poly)) return;
  const last = poly[poly.length - 1];
  const prev = poly[poly.length - 2] || last;
  poly.push([round2((last[0] + prev[0]) / 2), round2((last[1] + prev[1]) / 2)]);
  buildPanels();
  onMotionChanged(true);
}

function removeMaskVertex() {
  const key = getMaskFieldKey(state.motion);
  const poly = key && state.motion[key];
  if (!Array.isArray(poly) || poly.length <= 3) return;
  const match = /^mask:vertex:(\d+)$/.exec(state.selectedHandleId || "");
  const index = match ? parseInt(match[1], 10) : poly.length - 1;
  poly.splice(index, 1);
  state.selectedHandleId = null;
  buildPanels();
  onMotionChanged(true);
}

function buildMaskSection(container, motion) {
  const key = getMaskFieldKey(motion);
  if (!key) return;

  const heading = document.createElement("h3");
  heading.textContent = "Custom clip shape (optional, any vertex count)";
  container.appendChild(heading);

  if (!Array.isArray(motion[key])) {
    const note = document.createElement("p");
    note.className = "muted-note";
    note.textContent =
      motion.type === "surface_scan" || motion.type === "vertical_gear"
        ? "The quad above always drives the perspective and travel direction (locked to 4 corners). Add a separate free-form outline here for a non-quad visible shape."
        : "By default this clips to its full shape. Add a free-form outline here to restrict it to something else, like a non-rectangular cutout.";
    container.appendChild(note);
    const addButton = document.createElement("button");
    addButton.textContent = "+ Add custom clip shape";
    addButton.addEventListener("click", () => {
      let base;
      if (Array.isArray(motion.polygon) && key !== "polygon") {
        base = motion.polygon;
      } else if (Array.isArray(motion.bbox)) {
        const [x0, y0, x1, y1] = motion.bbox;
        base = [
          [x0, y0],
          [x1, y0],
          [x1, y1],
          [x0, y1],
        ];
      } else {
        base = [
          [0, 0],
          [10, 0],
          [10, 10],
          [0, 10],
        ];
      }
      motion[key] = JSON.parse(JSON.stringify(base));
      buildPanels();
      onMotionChanged(true);
    });
    container.appendChild(addButton);
    return;
  }

  motion[key].forEach((_, index) => {
    container.appendChild(
      vecRow(
        `Vertex ${index + 1}`,
        () => motion[key][index],
        (v) => {
          motion[key][index] = v;
        }
      )
    );
  });

  const buttonRow = document.createElement("div");
  buttonRow.className = "button-row";
  const addVertexButton = document.createElement("button");
  addVertexButton.textContent = "+ Add vertex";
  addVertexButton.addEventListener("click", addMaskVertex);
  const removeVertexButton = document.createElement("button");
  removeVertexButton.textContent = "− Remove vertex";
  removeVertexButton.disabled = motion[key].length <= 3;
  removeVertexButton.addEventListener("click", removeMaskVertex);
  const removeShapeButton = document.createElement("button");
  removeShapeButton.className = "danger";
  removeShapeButton.textContent = "Remove custom clip shape";
  removeShapeButton.addEventListener("click", () => {
    delete motion[key];
    buildPanels();
    onMotionChanged(true);
  });
  buttonRow.appendChild(addVertexButton);
  buttonRow.appendChild(removeVertexButton);
  buttonRow.appendChild(removeShapeButton);
  container.appendChild(buttonRow);
}

function shapeSection(container, motion, shape) {
  if (shape.kind === "polygon") {
    motion.polygon.forEach((_, index) => {
      container.appendChild(
        vecRow(
          `Vertex ${index + 1}`,
          () => motion.polygon[index],
          (v) => {
            motion.polygon[index] = v;
          }
        )
      );
    });
    const note = document.createElement("p");
    note.className = "muted-note";
    note.textContent = "Drag a vertex to reshape it, or drag the white center handle to move the whole shape.";
    container.appendChild(note);
  } else if (shape.kind === "bbox") {
    container.appendChild(
      vecRow(
        "Top-left",
        () => [motion.bbox[0], motion.bbox[1]],
        (v) => {
          motion.bbox[0] = v[0];
          motion.bbox[1] = v[1];
        }
      )
    );
    container.appendChild(
      vecRow(
        "Bottom-right",
        () => [motion.bbox[2], motion.bbox[3]],
        (v) => {
          motion.bbox[2] = v[0];
          motion.bbox[3] = v[1];
        }
      )
    );
  } else if (shape.kind === "points") {
    motion.points.forEach((_, index) => {
      container.appendChild(
        vecRow(
          `Point ${index + 1}`,
          () => [motion.points[index][0], motion.points[index][1]],
          (v) => {
            motion.points[index][0] = v[0];
            motion.points[index][1] = v[1];
          }
        )
      );
    });
    if (shape.radiusKey) {
      container.appendChild(
        vecRow(
          "Radius (x, y) — shared",
          () => motion[shape.radiusKey],
          (v) => {
            motion[shape.radiusKey] = v;
          }
        )
      );
    }
  } else if (shape.kind === "point") {
    container.appendChild(
      vecRow(
        "Position",
        () => motion[shape.key],
        (v) => {
          motion[shape.key] = v;
        }
      )
    );
    if (shape.radiusKey) {
      container.appendChild(
        vecRow(
          "Radius (x, y)",
          () => motion[shape.radiusKey],
          (v) => {
            motion[shape.radiusKey] = v;
          }
        )
      );
    }
  } else if (shape.kind === "ellipseRing") {
    container.appendChild(
      vecRow(
        "Center (x, y)",
        () => motion.center,
        (value) => {
          const previousY = motion.center[1];
          motion.center = value;
          const dy = value[1] - previousY;
          if (motion.minimum_y !== undefined) motion.minimum_y = round2(motion.minimum_y + dy);
          if (motion.maximum_y !== undefined) motion.maximum_y = round2(motion.maximum_y + dy);
        }
      )
    );
    container.appendChild(
      vecRow(
        "Outer radius (x, y)",
        () => motion.outer_radius,
        (value) => {
          motion.outer_radius = [Math.max(0.5, Math.abs(value[0])), Math.max(0.5, Math.abs(value[1]))];
        }
      )
    );
    container.appendChild(
      vecRow(
        "Inner radius (x, y)",
        () => motion.inner_radius,
        (value) => {
          motion.inner_radius = [
            clamp(Math.abs(value[0]), 0.1, Math.max(0.1, motion.outer_radius[0] - 0.1)),
            clamp(Math.abs(value[1]), 0.1, Math.max(0.1, motion.outer_radius[1] - 0.1)),
          ];
        }
      )
    );
    container.appendChild(
      vecRow(
        "Visible Y range (min, max)",
        () => [motion.minimum_y, motion.maximum_y],
        (value) => {
          motion.minimum_y = Math.min(value[0], value[1]);
          motion.maximum_y = Math.max(value[0], value[1]);
        }
      )
    );
    const note = document.createElement("p");
    note.className = "muted-note";
    note.textContent =
      "Pink ellipses set the outer and inner edges. The dashed horizontal handles crop the ring vertically for half- and quarter-ring foreground pieces.";
    container.appendChild(note);
  }
}

const COMMON_FIELD_SPECS = [
  { key: "axis", kind: "select", options: ["x", "y"] },
  { key: "color", kind: "color" },
  { key: "alpha", kind: "slider", min: 0, max: 255, step: 1 },
  { key: "blur", kind: "slider", min: 0, max: 10, step: 0.1 },
  { key: "width", kind: "number", step: 1 },
  { key: "phase", kind: "slider", min: 0, max: 1, step: 0.01 },
  { key: "travel", kind: "number", step: 1 },
  { key: "count", kind: "number", step: 1 },
  { key: "start_angle", kind: "number", step: 1 },
  { key: "end_angle", kind: "number", step: 1 },
  { key: "rise", kind: "number", step: 1 },
  { key: "drift", kind: "number", step: 0.5 },
  { key: "turns", kind: "number", step: 0.1 },
  { key: "dot_radius", kind: "number", step: 0.5 },
  { key: "fade_power", kind: "number", step: 0.1 },
  { key: "orbit_x", kind: "number", step: 0.01 },
  { key: "orbit_y", kind: "number", step: 0.01 },
];

function rgbToHex(rgb) {
  return "#" + rgb.slice(0, 3).map((v) => clamp(Math.round(v), 0, 255).toString(16).padStart(2, "0")).join("");
}
function hexToRgb(hex) {
  return [1, 3, 5].map((i) => parseInt(hex.substr(i, 2), 16));
}

function colorRow(label, getRGB, setRGB) {
  const wrap = row(label);
  const input = document.createElement("input");
  input.type = "color";
  input.value = rgbToHex(getRGB());
  input.addEventListener("input", () => {
    setRGB(hexToRgb(input.value));
    onMotionChanged();
  });
  wrap.appendChild(input);
  wrap._refresh = () => {
    if (document.activeElement !== input) input.value = rgbToHex(getRGB());
  };
  state.refreshCallbacks.push(wrap._refresh);
  return wrap;
}

const GAUGE_THEMES = [
  {
    label: "Brass gauge",
    description: "Dark charcoal face with a warm brass rim and cream ticks -- the classic default look.",
    values: {
      face_color: [57, 51, 42],
      rim_color: [137, 102, 57],
      rim_shadow_color: [48, 38, 29],
      tick_color: [225, 204, 153],
      needle_color: [196, 68, 49],
      edge_color: [67, 31, 24],
      highlight_color: [245, 163, 118],
      pivot_color: [116, 91, 61],
    },
  },
  {
    label: "Ivory face",
    description: "White/beige face with dark ticks and a dark needle -- reads clean against most sprites.",
    recommended: true,
    values: {
      face_color: [235, 227, 208],
      rim_color: [196, 182, 150],
      rim_shadow_color: [163, 148, 116],
      tick_color: [45, 40, 34],
      needle_color: [40, 36, 30],
      edge_color: [20, 18, 15],
      highlight_color: [140, 132, 118],
      pivot_color: [55, 50, 42],
    },
  },
  {
    label: "Steel gauge",
    description: "Cool grey metal face with black ticks and a red-orange needle for high contrast.",
    values: {
      face_color: [200, 203, 206],
      rim_color: [90, 94, 98],
      rim_shadow_color: [58, 61, 64],
      tick_color: [22, 22, 24],
      needle_color: [214, 90, 46],
      edge_color: [70, 32, 16],
      highlight_color: [245, 178, 140],
      pivot_color: [48, 50, 52],
    },
  },
];

function setGaugeTheme(motion, values) {
  for (const [key, value] of Object.entries(values)) motion[key] = value;
}

// Chase points are [x, y] or, when a per-dot color override is baked in,
// [x, y, r, g, b] -- generate_animations.py's add_chase falls back to a
// shared top-level `color` only for points that lack the 5-tuple override.
// Every real chase in animations.json embeds the *same* rgb on each point,
// so treating it as one shared color (synced onto every point plus the
// top-level fallback) is what the UI exposes, rather than surfacing five
// unlinked color pickers.
function getChaseColor(motion) {
  const first = motion.points[0];
  if (first && first.length >= 5) return first.slice(2, 5);
  return motion.color || [255, 190, 70];
}
function setChaseColor(motion, rgb) {
  for (const point of motion.points) {
    point[2] = rgb[0];
    point[3] = rgb[1];
    point[4] = rgb[2];
  }
}
function setChasePointCount(motion, count) {
  const points = motion.points;
  count = Math.max(1, Math.round(count));
  while (points.length < count) {
    const last = points[points.length - 1];
    const prev = points[points.length - 2] || last;
    const dx = last[0] - prev[0] || 15;
    const dy = last[1] - prev[1] || 0;
    points.push([round2(last[0] + dx), round2(last[1] + dy), ...getChaseColor(motion)]);
  }
  while (points.length > count) points.pop();
}

function buildChasePanels(motion) {
  const heading = document.createElement("h2");
  heading.textContent = "Position / shape";
  genericPanel.appendChild(heading);
  shapeSection(genericPanel, motion, getShapeSpec(motion));

  const dotsHeading = document.createElement("h2");
  dotsHeading.textContent = "Chase dots";
  genericPanel.appendChild(dotsHeading);

  const countWrap = row("Point count");
  const countInput = numberInput(motion.points.length, (value) => {
    setChasePointCount(motion, value);
    buildPanels();
    onMotionChanged(true);
  }, "1");
  countWrap.appendChild(countInput);
  genericPanel.appendChild(countWrap);

  genericPanel.appendChild(
    colorRow("Dot color", () => getChaseColor(motion), (rgb) => {
      setChaseColor(motion, rgb);
    })
  );

  const note = document.createElement("p");
  note.className = "muted-note";
  note.textContent = "All dots in this chase share one color. Adding a point copies the spacing of the last two dots.";
  genericPanel.appendChild(note);
}

// Only meaningful when sweep's axis (set in Common parameters, below) is
// "circle"/"-circle" -- center/min_radius/max_radius are otherwise unread by
// add_sweep(). Defaults mirror generate_animations.py's fallbacks (bbox
// center, 0, half the bbox diagonal) so the fields show a sensible starting
// point even before the user has ever touched them.
function buildSweepCircleSection(container, motion) {
  const heading = document.createElement("h2");
  heading.textContent = "Circle sweep";
  container.appendChild(heading);

  const note = document.createElement("p");
  note.className = "muted-note";
  note.textContent = "Only used when Travel axis (under Common parameters, below) is circle or -circle.";
  container.appendChild(note);

  const [x0, y0, x1, y1] = motion.bbox;
  const defaultCenter = [round2((x0 + x1) / 2), round2((y0 + y1) / 2)];
  const defaultMaxRadius = round2(Math.hypot(x1 - x0, y1 - y0) / 2);

  container.appendChild(
    vecRow("Circle center (x, y)", () => motion.center || defaultCenter, (value) => {
      motion.center = value;
    })
  );
  container.appendChild(
    vecRow(
      "Radius range (min, max)",
      () => [motion.min_radius ?? 0, motion.max_radius ?? defaultMaxRadius],
      (value) => {
        motion.min_radius = Math.max(0, value[0]);
        motion.max_radius = Math.max(motion.min_radius, value[1]);
      }
    )
  );
}

function buildLayerLightingSection(container, motion) {
  const heading = document.createElement("h2");
  heading.textContent = "Lighting";
  container.appendChild(heading);

  const lighting = motion.lighting || { mode: "global" };
  const modeRow = row("Light source");
  const modeSelect = document.createElement("select");
  for (const [value, label] of [
    ["global", "Follow asset global light"],
    ["custom", "Custom for this layer"],
  ]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    option.selected = (lighting.mode || "global") === value;
    modeSelect.appendChild(option);
  }
  modeSelect.addEventListener("change", () => {
    motion.lighting = { ...lighting, mode: modeSelect.value };
    buildPanels();
    onMotionChanged(true);
  });
  modeRow.appendChild(modeSelect);
  container.appendChild(modeRow);

  if (lighting.mode === "custom") {
    const directionRow = row("Direction");
    directionRow.appendChild(
      numberInput(lighting.direction_degrees ?? 35, (value) => {
        motion.lighting.direction_degrees = clamp(value, 0, 360);
        onMotionChanged();
      }, "1")
    );
    const suffix = document.createElement("span");
    suffix.className = "value";
    suffix.textContent = "° from left";
    directionRow.appendChild(suffix);
    container.appendChild(directionRow);
    for (const [label, key, fallback] of [
      ["Directional strength", "strength", DEFAULT_LIGHTING.strength],
      ["Ambient light", "ambient", DEFAULT_LIGHTING.ambient],
    ]) {
      container.appendChild(
        sliderRow(label, lighting[key] ?? fallback, 0, 1, 0.01, (value) => {
          motion.lighting[key] = value;
        })
      );
    }
  }
  const note = document.createElement("p");
  note.className = "muted-note";
  note.textContent =
    "Used by generated material surfaces such as cogs, rotors, edge-on gears, and gauges.";
  container.appendChild(note);
}

function buildCommonPanel(container, motion) {
  buildLayerLightingSection(container, motion);
  const applicable = COMMON_FIELD_SPECS.filter((spec) => motion[spec.key] !== undefined);
  if (applicable.length === 0) return;
  const heading = document.createElement("h2");
  heading.textContent = "Common parameters";
  container.appendChild(heading);
  for (const spec of applicable) {
    if (spec.kind === "select") {
      const wrap = row(spec.key);
      const select = document.createElement("select");
      // sweep and surface_scan support reverse travel (-x/-y); circle/-circle
      // (radial ring around a defined center) is sweep-only. Other axis-having
      // motions don't read a leading "-" or "circle" in generate_animations.py.
      const options =
        spec.key === "axis" && (motion.type === "sweep" || motion.type === "surface_scan")
          ? [
              ["x", "x → (left to right)"],
              ["-x", "-x ← (right to left)"],
              ["y", "y ↓ (top to bottom)"],
              ["-y", "-y ↑ (bottom to top)"],
              ...(motion.type === "sweep"
                ? [
                    ["circle", "circle ↗ (outward)"],
                    ["-circle", "-circle ↙ (inward)"],
                  ]
                : []),
            ]
          : spec.options.map((value) => [value, value]);
      for (const [optionValue, optionLabel] of options) {
        const option = document.createElement("option");
        option.value = optionValue;
        option.textContent = optionLabel;
        if ((motion[spec.key] ?? "x") === optionValue) option.selected = true;
        select.appendChild(option);
      }
      select.addEventListener("change", () => {
        motion[spec.key] = select.value;
        // Switching sweep's axis in/out of circle mode changes which fields
        // (position strip vs. center/radius) are relevant, so rebuild panels.
        if (spec.key === "axis" && motion.type === "sweep") {
          buildPanels();
          onMotionChanged(true);
        } else {
          onMotionChanged();
        }
      });
      wrap.appendChild(select);
      container.appendChild(wrap);
    } else if (spec.kind === "slider") {
      container.appendChild(
        sliderRow(spec.key, motion[spec.key], spec.min, spec.max, spec.step, (v) => {
          motion[spec.key] = v;
        })
      );
    } else if (spec.kind === "number") {
      const wrap = row(spec.key);
      const input = numberInput(
        motion[spec.key],
        (v) => {
          motion[spec.key] = v;
          onMotionChanged();
        },
        String(spec.step)
      );
      wrap.appendChild(input);
      container.appendChild(wrap);
    } else if (spec.kind === "color") {
      container.appendChild(
        colorRow("Color", () => motion.color, (rgb) => {
          motion.color = rgb;
        })
      );
    }
  }
}

function verticalGearAxisPoint(motion, t) {
  const [topLeft, topRight, bottomRight, bottomLeft] = motion.polygon;
  if ((motion.axis ?? "y") === "y") {
    const start = [(topLeft[0] + topRight[0]) / 2, (topLeft[1] + topRight[1]) / 2];
    const end = [(bottomLeft[0] + bottomRight[0]) / 2, (bottomLeft[1] + bottomRight[1]) / 2];
    return [round2(start[0] + (end[0] - start[0]) * t), round2(start[1] + (end[1] - start[1]) * t)];
  }
  const start = [(topLeft[0] + bottomLeft[0]) / 2, (topLeft[1] + bottomLeft[1]) / 2];
  const end = [(topRight[0] + bottomRight[0]) / 2, (topRight[1] + bottomRight[1]) / 2];
  return [round2(start[0] + (end[0] - start[0]) * t), round2(start[1] + (end[1] - start[1]) * t)];
}

const VERTICAL_GEAR_PRESETS = [
  {
    label: "Subtle",
    description: "Shallow teeth and soft contrast for small or distant machinery.",
    values: {
      tooth_depth_fraction: 0.3,
      side_depth_fraction: 0.11,
      root_face_brightness: 0.73,
      cavity_brightness: 0.36,
      side_face_brightness: 0.62,
      face_texture_strength: 0.06,
      root_shadow_strength: 0.16,
      tip_highlight_strength: 0.12,
      highlight_strength: 0.18,
      shadow_strength: 0.25,
      side_face_strength: 0.2,
      side_shadow_strength: 0.28,
    },
  },
  {
    label: "Balanced",
    description: "Recommended: clear 3D teeth while preserving the source sprite.",
    recommended: true,
    values: {
      tooth_depth_fraction: 0.48,
      side_depth_fraction: 0.24,
      root_face_brightness: 0.62,
      cavity_brightness: 0.24,
      side_face_brightness: 0.54,
      face_texture_strength: 0.14,
      root_shadow_strength: 0.31,
      tip_highlight_strength: 0.24,
      highlight_strength: 0.28,
      shadow_strength: 0.39,
      side_face_strength: 0.31,
      side_shadow_strength: 0.42,
    },
  },
  {
    label: "Chunky 3D",
    description: "Deep, high-contrast teeth for large mechanisms and close views.",
    values: {
      tooth_depth_fraction: 0.62,
      side_depth_fraction: 0.34,
      root_face_brightness: 0.55,
      cavity_brightness: 0.15,
      side_face_brightness: 0.49,
      face_texture_strength: 0.18,
      root_shadow_strength: 0.42,
      tip_highlight_strength: 0.36,
      highlight_strength: 0.34,
      shadow_strength: 0.5,
      side_face_strength: 0.42,
      side_shadow_strength: 0.55,
    },
  },
];

function setVerticalGearAppearance(motion, values) {
  for (const [key, value] of Object.entries(values)) motion[key] = value;
}

function verticalGearStrengthPercent(motion) {
  return Math.round(clamp(((motion.tooth_depth_fraction ?? 0.42) - 0.18) / 0.52, 0, 1) * 100);
}

function setVerticalGearStrength(motion, percent) {
  const amount = clamp(percent / 100, 0, 1);
  setVerticalGearAppearance(motion, {
    tooth_depth_fraction: round2(0.18 + 0.52 * amount),
    side_depth_fraction: round2(0.06 + 0.34 * amount),
    root_face_brightness: round2(0.74 - 0.18 * amount),
    cavity_brightness: round2(0.42 - 0.25 * amount),
    side_face_brightness: round2(0.66 - 0.17 * amount),
    root_shadow_strength: round2(0.12 + 0.34 * amount),
    tip_highlight_strength: round2(0.1 + 0.27 * amount),
  });
}

function verticalGearGapDarknessPercent(motion) {
  return Math.round(clamp((0.6 - (motion.cavity_brightness ?? 0.28)) / 0.52, 0, 1) * 100);
}

function buildVerticalGearPanels(motion) {
  if (!Array.isArray(motion.middle)) motion.middle = verticalGearAxisPoint(motion, 0.5);
  if (motion.arc_start_degrees === undefined) motion.arc_start_degrees = 90;
  if (motion.arc_end_degrees === undefined) motion.arc_end_degrees = 90;
  const heading = document.createElement("h2");
  heading.textContent = "Vertical gear (edge-on rim)";
  geometryPanel.appendChild(heading);
  const intro = document.createElement("p");
  intro.className = "muted-note";
  intro.textContent =
    "Fit the four orange corners to the visible toothed strip in this order: top-left, top-right, " +
    "bottom-right, bottom-left. The blue middle line is the tangent: teeth move fastest there and " +
    "slow toward the circular limbs.";
  geometryPanel.appendChild(intro);

  const modeRow = row("Editor mode");
  const modeSelect = document.createElement("select");
  for (const [value, label] of [["simple", "Simple (recommended)"], ["advanced", "Advanced"]]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    if ((state.verticalGearAdvanced ? "advanced" : "simple") === value) option.selected = true;
    modeSelect.appendChild(option);
  }
  modeSelect.addEventListener("change", () => {
    state.verticalGearAdvanced = modeSelect.value === "advanced";
    buildPanels();
  });
  modeRow.appendChild(modeSelect);
  geometryPanel.appendChild(modeRow);
  if (state.verticalGearAdvanced) {
    shapeSection(geometryPanel, motion, getShapeSpec(motion));
  } else {
    const simpleGeometryNote = document.createElement("p");
    simpleGeometryNote.className = "muted-note simple-callout";
    simpleGeometryNote.textContent =
      "Drag the four orange corners directly on the image to fit the gear. Numeric coordinates are available in Advanced mode.";
    geometryPanel.appendChild(simpleGeometryNote);
  }
  if (state.verticalGearAdvanced) {
    geometryPanel.appendChild(
      vecRow(
        "Tangent / middle point",
        () => motion.middle,
        (value) => {
          motion.middle = value;
        }
      )
    );
  }
  const middleButtons = document.createElement("div");
  middleButtons.className = "button-row";
  for (const [label, t] of [
    ["Half gear (center)", 0.5],
    ["Quarter from start", 0],
    ["Quarter from end", 1],
  ]) {
    const button = document.createElement("button");
    button.textContent = label;
    button.addEventListener("click", () => {
      motion.middle = verticalGearAxisPoint(motion, t);
      buildPanels();
      onMotionChanged(true);
    });
    middleButtons.appendChild(button);
  }
  geometryPanel.appendChild(middleButtons);
  const middleNote = document.createElement("p");
  middleNote.className = "muted-note";
  middleNote.textContent =
    "Move the tangent to a strip end for one visible quarter-arc, or anywhere between for an asymmetric partial gear.";
  geometryPanel.appendChild(middleNote);
  if (state.verticalGearAdvanced) buildMaskSection(geometryPanel, motion);

  const motionHeading = document.createElement("h2");
  motionHeading.textContent = "Tooth travel";
  secondaryPanel.appendChild(motionHeading);

  if (state.verticalGearAdvanced) {
    const axisRow = row("Travel axis");
    const axisSelect = document.createElement("select");
    for (const [value, label] of [
      ["y", "top ↕ bottom (axle X)"],
      ["x", "left ↔ right (axle Y)"],
    ]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      if ((motion.axis ?? "y") === value) option.selected = true;
      axisSelect.appendChild(option);
    }
    axisSelect.addEventListener("change", () => {
      motion.axis = axisSelect.value;
      buildPanels();
      onMotionChanged(true);
    });
    axisRow.appendChild(axisSelect);
    secondaryPanel.appendChild(axisRow);
  }

  const directionRow = row("Direction");
  const directionSelect = document.createElement("select");
  const vertical = (motion.axis ?? "y") === "y";
  for (const value of [1, -1]) {
    const option = document.createElement("option");
    option.value = String(value);
    option.textContent = vertical
      ? value === 1
        ? "1 (top → bottom)"
        : "-1 (bottom → top)"
      : value === 1
        ? "1 (left → right)"
        : "-1 (right → left)";
    if ((motion.direction ?? 1) === value) option.selected = true;
    directionSelect.appendChild(option);
  }
  directionSelect.addEventListener("change", () => {
    motion.direction = parseInt(directionSelect.value, 10);
    onMotionChanged(true);
  });
  directionRow.appendChild(directionSelect);
  secondaryPanel.appendChild(directionRow);

  for (const [label, key, fallback, minimum] of [
    ["Number of teeth", "tooth_count", 8, 2],
    ["Animation speed", "pitches_per_loop", 1, 1],
  ]) {
    const wrap = row(label);
    const input = numberInput(motion[key] ?? fallback, (value) => {
      motion[key] = Math.max(minimum, Math.round(value));
      onMotionChanged();
    }, "1");
    wrap.appendChild(input);
    secondaryPanel.appendChild(wrap);
  }
  if (state.verticalGearAdvanced) {
    const supersampleRow = row("Supersample");
    supersampleRow.appendChild(numberInput(motion.supersample ?? 6, (value) => {
      motion.supersample = Math.max(1, Math.round(value));
      onMotionChanged();
    }, "1"));
    secondaryPanel.appendChild(supersampleRow);
    secondaryPanel.appendChild(
      sliderRow("Arc to strip start (degrees)", motion.arc_start_degrees ?? 90, 1, 90, 1, (value) => {
        motion.arc_start_degrees = value;
      })
    );
    secondaryPanel.appendChild(
      sliderRow("Arc to strip end (degrees)", motion.arc_end_degrees ?? 90, 1, 90, 1, (value) => {
        motion.arc_end_degrees = value;
      })
    );
    secondaryPanel.appendChild(
      sliderRow("Starting tooth phase", motion.phase ?? 0, 0, 1, 0.005, (value) => {
        motion.phase = value;
      })
    );
    secondaryPanel.appendChild(
      sliderRow("Edge feather", motion.aperture_feather ?? 0.55, 0, 1.5, 0.01, (value) => {
        motion.aperture_feather = value;
      })
    );
  }
  const closureNote = document.createElement("p");
  closureNote.className = "muted-note";
  closureNote.textContent =
    state.verticalGearAdvanced
      ? "Direction is visible rim travel, not a universal clockwise label. Tooth count covers the full 360° wheel. " +
        "Animation speed advances an exact number of tooth pitches per loop, keeping frame 24 identical to frame 0."
      : "Usually you only need direction, number of teeth, and animation speed. Use the presets below for appearance.";
  secondaryPanel.appendChild(closureNote);

  const materialHeading = document.createElement("h2");
  materialHeading.textContent = state.verticalGearAdvanced ? "3D tooth volume + material" : "Gear appearance";
  genericPanel.appendChild(materialHeading);

  const presetLabel = document.createElement("p");
  presetLabel.className = "muted-note";
  presetLabel.textContent = "Start with a preset, then adjust only what looks wrong.";
  genericPanel.appendChild(presetLabel);
  const presetButtons = document.createElement("div");
  presetButtons.className = "button-row gear-presets";
  for (const preset of VERTICAL_GEAR_PRESETS) {
    const button = document.createElement("button");
    button.textContent = preset.label;
    button.title = preset.description;
    if (preset.recommended) button.className = "primary";
    button.addEventListener("click", () => {
      setVerticalGearAppearance(motion, preset.values);
      buildPanels();
      onMotionChanged(true);
    });
    presetButtons.appendChild(button);
  }
  genericPanel.appendChild(presetButtons);

  genericPanel.appendChild(
    sliderRow("3D amount (%)", verticalGearStrengthPercent(motion), 0, 100, 1, (value) => {
      setVerticalGearStrength(motion, value);
    })
  );
  genericPanel.appendChild(
    sliderRow("Gap darkness (%)", verticalGearGapDarknessPercent(motion), 0, 100, 1, (value) => {
      motion.cavity_brightness = round2(0.6 - 0.52 * clamp(value / 100, 0, 1));
    })
  );
  genericPanel.appendChild(
    sliderRow(
      "Tooth width (%)",
      Math.round(clamp(((motion.tooth_width_fraction ?? 0.52) - 0.18) / 0.68, 0, 1) * 100),
      0,
      100,
      1,
      (value) => {
        motion.tooth_width_fraction = round2(0.18 + 0.68 * clamp(value / 100, 0, 1));
      }
    )
  );
  genericPanel.appendChild(
    sliderRow(
      "Surface detail (%)",
      Math.round(clamp((motion.face_texture_strength ?? 0.1) / 0.28, 0, 1) * 100),
      0,
      100,
      1,
      (value) => {
        motion.face_texture_strength = round2(0.28 * clamp(value / 100, 0, 1));
      }
    )
  );

  const materialToggle = row("Use source tooth detail");
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = motion.source_tooth_material !== false;
  checkbox.addEventListener("change", () => {
    motion.source_tooth_material = checkbox.checked;
    onMotionChanged(true);
  });
  materialToggle.appendChild(checkbox);
  if (state.verticalGearAdvanced) genericPanel.appendChild(materialToggle);

  const outerEdgeRow = row("Toothed outer edge");
  const outerEdgeSelect = document.createElement("select");
  const outerEdgeLabels = vertical
    ? [["start", "left quad edge"], ["end", "right quad edge"]]
    : [["start", "top quad edge"], ["end", "bottom quad edge"]];
  for (const [value, label] of outerEdgeLabels) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    if ((motion.outer_edge ?? "start") === value) option.selected = true;
    outerEdgeSelect.appendChild(option);
  }
  outerEdgeSelect.addEventListener("change", () => {
    motion.outer_edge = outerEdgeSelect.value;
    onMotionChanged(true);
  });
  outerEdgeRow.appendChild(outerEdgeSelect);
  genericPanel.appendChild(outerEdgeRow);

  if (state.verticalGearAdvanced) for (const [label, key, fallback, min, max, step] of [
    ["Moving source blend", "source_material_blend", 0.82, 0, 1, 0.01],
    ["Source detail strength", "source_detail_strength", 0.88, 0, 1.5, 0.01],
    ["Fixed shading blur", "material_blur", 1.6, 0.2, 5, 0.05],
    ["Tooth width", "tooth_width_fraction", 0.52, 0.12, 0.9, 0.01],
    ["Tooth protrusion depth", "tooth_depth_fraction", 0.42, 0.06, 0.82, 0.01],
    ["Silhouette softness", "silhouette_softness", 0.025, 0.006, 0.16, 0.002],
    ["3D side-wall depth", "side_depth_fraction", 0.2, 0, 0.48, 0.005],
    ["Root cylinder brightness", "root_face_brightness", 0.64, 0.15, 1.2, 0.01],
    ["Recess brightness", "cavity_brightness", 0.28, 0.05, 0.9, 0.01],
    ["Side-face brightness", "side_face_brightness", 0.56, 0.1, 1.1, 0.01],
    ["Moving face texture", "face_texture_strength", 0.1, 0, 0.35, 0.005],
    ["Root self-shadow", "root_shadow_strength", 0.24, 0, 0.7, 0.01],
    ["Outer tip highlight", "tip_highlight_strength", 0.18, 0, 0.65, 0.01],
    ["Edge softness", "edge_softness", 0.065, 0.012, 0.24, 0.002],
    ["Highlight relief", "highlight_strength", 0.18, 0, 0.6, 0.01],
    ["Shadow relief", "shadow_strength", 0.24, 0, 0.7, 0.01],
    ["Groove darkness", "groove_strength", 0.075, 0, 0.4, 0.005],
    ["Groove visibility at center", "groove_visibility_power", 0.62, 0.1, 2.5, 0.01],
    ["Tooth-side visibility at limbs", "side_visibility_power", 0.58, 0.1, 2.5, 0.01],
    ["Visible tooth-side light", "side_face_strength", 0.26, 0, 0.8, 0.01],
    ["Occluded tooth-side shadow", "side_shadow_strength", 0.34, 0, 0.9, 0.01],
    ["Limb gap shadow", "side_gap_shadow", 0.1, 0, 0.5, 0.01],
    ["Moving detail at limbs", "edge_material_floor", 0.22, 0, 1, 0.01],
    ["Limb occlusion falloff", "edge_occlusion_power", 0.72, 0.1, 3, 0.01],
  ]) {
    genericPanel.appendChild(
      sliderRow(label, motion[key] ?? fallback, min, max, step, (value) => {
        motion[key] = value;
      })
    );
  }

  if (state.verticalGearAdvanced) {
    const lightRow = row("Highlight side");
    const lightSelect = document.createElement("select");
    for (const [value, label] of [
      [1, "strip start / top"],
      [-1, "strip end / bottom"],
    ]) {
      const option = document.createElement("option");
      option.value = String(value);
      option.textContent = label;
      if ((motion.light_direction ?? 1) === value) option.selected = true;
      lightSelect.appendChild(option);
    }
    lightSelect.addEventListener("change", () => {
      motion.light_direction = parseInt(lightSelect.value, 10);
      onMotionChanged(true);
    });
    lightRow.appendChild(lightSelect);
    genericPanel.appendChild(lightRow);
  }

  const materialNote = document.createElement("p");
  materialNote.className = "muted-note";
  materialNote.textContent =
    state.verticalGearAdvanced
      ? "The outer band is actual moving geometry: tooth tops protrude over a darker root cylinder, gaps expose a recessed " +
        "cavity, and swept side walls self-occlude toward each limb. Source material moves with the tooth while broad lighting stays fixed."
      : "3D amount controls tooth depth, side walls, highlights and self-shadow together. Gap darkness controls the recessed spaces. " +
        "Switch Editor mode to Advanced only when a preset cannot match the sprite.";
  genericPanel.appendChild(materialNote);
}

function addVibrationVertex(motion) {
  if (!Array.isArray(motion.polygon) || motion.polygon.length < 2) return;
  let insertAfter = -1;
  let longest = -1;
  for (let index = 0; index < motion.polygon.length; index++) {
    const a = motion.polygon[index];
    const b = motion.polygon[(index + 1) % motion.polygon.length];
    const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
    if (length > longest) {
      longest = length;
      insertAfter = index;
    }
  }
  const selected = /^shape:vertex:(\d+)$/.exec(state.selectedHandleId || "");
  if (selected) insertAfter = parseInt(selected[1], 10);
  const a = motion.polygon[insertAfter];
  const b = motion.polygon[(insertAfter + 1) % motion.polygon.length];
  motion.polygon.splice(insertAfter + 1, 0, [round2((a[0] + b[0]) / 2), round2((a[1] + b[1]) / 2)]);
  state.selectedHandleId = `shape:vertex:${insertAfter + 1}`;
  buildPanels();
  onMotionChanged(true);
}

function removeVibrationVertex(motion) {
  if (!Array.isArray(motion.polygon) || motion.polygon.length <= 3) return;
  const selected = /^shape:vertex:(\d+)$/.exec(state.selectedHandleId || "");
  const index = selected ? parseInt(selected[1], 10) : motion.polygon.length - 1;
  motion.polygon.splice(index, 1);
  state.selectedHandleId = null;
  buildPanels();
  onMotionChanged(true);
}

function buildSourceOccluderPanels(motion) {
  const asset = state.asset;
  const [assetWidth, assetHeight] = asset.size;
  const heading = document.createElement("h2");
  heading.textContent = "Editable foreground occluder";
  geometryPanel.appendChild(heading);

  const intro = document.createElement("p");
  intro.className = "muted-note";
  intro.textContent =
    "This layer restores the untouched source sprite inside its pink shape. Put it after a cog or fan to hide only the parts that should pass behind foreground artwork.";
  geometryPanel.appendChild(intro);

  const nameRow = row("Layer name");
  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.placeholder = "for example: upper gear arch";
  nameInput.value = motion.label || "";
  nameInput.addEventListener("input", () => {
    if (nameInput.value.trim()) motion.label = nameInput.value.trim();
    else delete motion.label;
    renderLayerList();
    onMotionChanged();
  });
  nameRow.appendChild(nameInput);
  geometryPanel.appendChild(nameRow);

  const shapeRow = row("Shape");
  const shapeSelect = document.createElement("select");
  for (const [value, label] of [
    ["polygon", "polygon (freeform foreground)"],
    ["ellipse_ring", "ellipse ring (rim / arch)"],
  ]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    if ((motion.shape || "polygon") === value) option.selected = true;
    shapeSelect.appendChild(option);
  }
  shapeSelect.addEventListener("change", () => {
    if (shapeSelect.value === "ellipse_ring") {
      const points = Array.isArray(motion.polygon) && motion.polygon.length >= 3
        ? motion.polygon
        : [[assetWidth * 0.35, assetHeight * 0.35], [assetWidth * 0.65, assetHeight * 0.65]];
      const xs = points.map((point) => point[0]);
      const ys = points.map((point) => point[1]);
      const x0 = Math.min(...xs);
      const x1 = Math.max(...xs);
      const y0 = Math.min(...ys);
      const y1 = Math.max(...ys);
      const outer = [Math.max(1, round2((x1 - x0) / 2)), Math.max(1, round2((y1 - y0) / 2))];
      motion.shape = "ellipse_ring";
      motion.center = [round2((x0 + x1) / 2), round2((y0 + y1) / 2)];
      motion.outer_radius = outer;
      motion.inner_radius = [round2(outer[0] * 0.76), round2(outer[1] * 0.76)];
      motion.minimum_y = round2(y0);
      motion.maximum_y = round2(y1);
      motion.edge_feather = motion.edge_feather ?? 0.45;
      delete motion.polygon;
    } else {
      const center = motion.center || [assetWidth / 2, assetHeight / 2];
      const outer = motion.outer_radius || [assetWidth * 0.15, assetHeight * 0.1];
      motion.shape = "polygon";
      motion.polygon = [
        [round2(center[0] - outer[0]), round2(center[1] - outer[1])],
        [round2(center[0] + outer[0]), round2(center[1] - outer[1])],
        [round2(center[0] + outer[0]), round2(center[1] + outer[1])],
        [round2(center[0] - outer[0]), round2(center[1] + outer[1])],
      ];
      delete motion.center;
      delete motion.outer_radius;
      delete motion.inner_radius;
      delete motion.minimum_y;
      delete motion.maximum_y;
      delete motion.edge_feather;
    }
    state.selectedHandleId = null;
    buildPanels();
    onMotionChanged(true);
  });
  shapeRow.appendChild(shapeSelect);
  geometryPanel.appendChild(shapeRow);

  shapeSection(geometryPanel, motion, getShapeSpec(motion));
  if (motion.shape === "polygon") {
    const vertexButtons = document.createElement("div");
    vertexButtons.className = "button-row";
    const addVertex = document.createElement("button");
    addVertex.textContent = "+ Split selected / longest edge";
    addVertex.addEventListener("click", () => addVibrationVertex(motion));
    const removeVertex = document.createElement("button");
    removeVertex.textContent = "− Remove selected vertex";
    removeVertex.disabled = motion.polygon.length <= 3;
    removeVertex.addEventListener("click", () => removeVibrationVertex(motion));
    vertexButtons.appendChild(addVertex);
    vertexButtons.appendChild(removeVertex);
    geometryPanel.appendChild(vertexButtons);
  } else {
    const fitButton = document.createElement("button");
    fitButton.textContent = "Use the complete ring";
    fitButton.addEventListener("click", () => {
      motion.minimum_y = round2(motion.center[1] - motion.outer_radius[1]);
      motion.maximum_y = round2(motion.center[1] + motion.outer_radius[1]);
      buildPanels();
      onMotionChanged(true);
    });
    geometryPanel.appendChild(fitButton);
    geometryPanel.appendChild(
      sliderRow("Ellipse edge feather", motion.edge_feather ?? 0.45, 0, 2.5, 0.01, (value) => {
        motion.edge_feather = value;
      })
    );
  }
  geometryPanel.appendChild(
    sliderRow("Final shape feather", motion.feather ?? 0.35, 0, 2.5, 0.01, (value) => {
      motion.feather = value;
    })
  );

  const orderHeading = document.createElement("h2");
  orderHeading.textContent = "Layer order";
  secondaryPanel.appendChild(orderHeading);
  const orderNote = document.createElement("p");
  orderNote.className = "muted-note";
  orderNote.textContent =
    "The occluder affects every animated layer below it and nothing above it. Use Send backward / Bring forward beside the layer picker to control exactly which animation gets cropped.";
  secondaryPanel.appendChild(orderNote);
}

function buildGaugePanels(motion) {
  const heading = document.createElement("h2");
  heading.textContent = "Gauge needle";
  geometryPanel.appendChild(heading);
  const intro = document.createElement("p");
  intro.className = "muted-note";
  intro.textContent =
    "Fit the pink face basis to the dial. The two white range handles set the needle's endpoints; the dark middle handle sets its reach. Perspective is inherited from the face basis.";
  geometryPanel.appendChild(intro);

  const nameRow = row("Layer name");
  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.placeholder = "for example: pressure gauge";
  nameInput.value = motion.label || "";
  nameInput.addEventListener("input", () => {
    if (nameInput.value.trim()) motion.label = nameInput.value.trim();
    else delete motion.label;
    renderLayerList();
    onMotionChanged();
  });
  nameRow.appendChild(nameInput);
  geometryPanel.appendChild(nameRow);

  const modeRow = row("Editor mode");
  const modeSelect = document.createElement("select");
  for (const [value, label] of [["simple", "Simple (recommended)"], ["advanced", "Advanced"]]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    if ((state.gaugeAdvanced ? "advanced" : "simple") === value) option.selected = true;
    modeSelect.appendChild(option);
  }
  modeSelect.addEventListener("change", () => {
    state.gaugeAdvanced = modeSelect.value === "advanced";
    buildPanels();
  });
  modeRow.appendChild(modeSelect);
  geometryPanel.appendChild(modeRow);

  planeSection(geometryPanel, motion, getPlanes(motion)[0]);
  for (const [label, key, fallback] of [
    ["Range start (degrees)", "minimum_angle_degrees", -150],
    ["Range end (degrees)", "maximum_angle_degrees", -30],
  ]) {
    const angleRow = row(label);
    angleRow.appendChild(
      numberInput(motion[key] ?? fallback, (value) => {
        motion[key] = round2(value);
        onMotionChanged();
      }, "0.5")
    );
    geometryPanel.appendChild(angleRow);
  }
  const angleNote = document.createElement("p");
  angleNote.className = "muted-note";
  angleNote.textContent =
    "Angle convention: 0° points right and −90° points up. Values may pass ±180° when the desired arc crosses the left side of the dial.";
  geometryPanel.appendChild(angleNote);
  const geometryFields = [
    ["Needle reach", "needle_length", 0.78, 0.05, 1.2, 0.01],
    ["Needle thickness", "needle_width", 0.055, 0.005, 0.2, 0.002],
  ];
  if (state.gaugeAdvanced) geometryFields.push(
    ["Needle tail", "tail_length", 0.12, 0, 0.45, 0.01],
    ["Pivot cap size", "pivot_radius", 0.1, 0.015, 0.3, 0.005]
  );
  for (const [label, key, fallback, min, max, step] of geometryFields) {
    geometryPanel.appendChild(
      sliderRow(label, motion[key] ?? fallback, min, max, step, (value) => {
        motion[key] = value;
      })
    );
  }

  const motionHeading = document.createElement("h2");
  motionHeading.textContent = "Gauge movement";
  secondaryPanel.appendChild(motionHeading);
  const waveformRow = row("Movement");
  const waveformSelect = document.createElement("select");
  for (const [value, label] of [
    ["sine", "smooth pressure swing (recommended)"],
    ["triangle", "constant-speed sweep"],
  ]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    if ((motion.waveform ?? "sine") === value) option.selected = true;
    waveformSelect.appendChild(option);
  }
  waveformSelect.addEventListener("change", () => {
    motion.waveform = waveformSelect.value;
    onMotionChanged(true);
  });
  waveformRow.appendChild(waveformSelect);
  secondaryPanel.appendChild(waveformRow);

  const cyclesRow = row("Swings / loop");
  cyclesRow.appendChild(
    numberInput(motion.cycles_per_loop ?? 1, (value) => {
      motion.cycles_per_loop = Math.max(1, Math.round(value));
      onMotionChanged();
    }, "1")
  );
  secondaryPanel.appendChild(cyclesRow);
  secondaryPanel.appendChild(
    sliderRow("Starting phase", motion.phase ?? 0, 0, 1, 0.005, (value) => {
      motion.phase = value;
    })
  );
  const directionRow = row("Direction");
  const directionSelect = document.createElement("select");
  for (const [value, label] of [["normal", "start → end first"], ["reverse", "end → start first"]]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    if ((motion.reverse ? "reverse" : "normal") === value) option.selected = true;
    directionSelect.appendChild(option);
  }
  directionSelect.addEventListener("change", () => {
    motion.reverse = directionSelect.value === "reverse";
    onMotionChanged(true);
  });
  directionRow.appendChild(directionSelect);
  secondaryPanel.appendChild(directionRow);
  const closureNote = document.createElement("p");
  closureNote.className = "muted-note";
  closureNote.textContent =
    "Swings / loop is kept integral, so the first and last frame meet exactly without a needle teleport.";
  secondaryPanel.appendChild(closureNote);

  const themeHeading = document.createElement("h2");
  themeHeading.textContent = "Color theme";
  genericPanel.appendChild(themeHeading);
  const themeLabel = document.createElement("p");
  themeLabel.className = "muted-note";
  themeLabel.textContent = "Sets face, rim, tick, and needle colors together. Pick one, then fine-tune individual colors below.";
  genericPanel.appendChild(themeLabel);
  const themeButtons = document.createElement("div");
  themeButtons.className = "button-row gauge-themes";
  for (const theme of GAUGE_THEMES) {
    const button = document.createElement("button");
    button.textContent = theme.label;
    button.title = theme.description;
    if (theme.recommended) button.className = "primary";
    button.addEventListener("click", () => {
      setGaugeTheme(motion, theme.values);
      buildPanels();
      onMotionChanged(true);
    });
    themeButtons.appendChild(button);
  }
  genericPanel.appendChild(themeButtons);

  const faceHeading = document.createElement("h2");
  faceHeading.textContent = "Gauge background";
  genericPanel.appendChild(faceHeading);
  const backgroundRow = row("Background");
  const backgroundSelect = document.createElement("select");
  for (const [value, label] of [
    ["full", "complete dial face (recommended)"],
    ["needle_only", "needle only (use source dial)"],
  ]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    if (((motion.background_enabled ?? true) ? "full" : "needle_only") === value) option.selected = true;
    backgroundSelect.appendChild(option);
  }
  backgroundSelect.addEventListener("change", () => {
    motion.background_enabled = backgroundSelect.value === "full";
    buildPanels();
    onMotionChanged(true);
  });
  backgroundRow.appendChild(backgroundSelect);
  genericPanel.appendChild(backgroundRow);
  if (motion.background_enabled ?? true) {
    const faceColors = [
      ["Face color", "face_color", [57, 51, 42]],
      ["Rim color", "rim_color", [137, 102, 57]],
      ["Tick color", "tick_color", [225, 204, 153]],
    ];
    if (state.gaugeAdvanced) faceColors.push(
      ["Rim shadow", "rim_shadow_color", [48, 38, 29]]
    );
    for (const [label, key, fallback] of faceColors) {
      genericPanel.appendChild(
        colorRow(label, () => motion[key] || fallback, (value) => {
          motion[key] = value;
        })
      );
    }
    if (state.gaugeAdvanced) {
      genericPanel.appendChild(
        sliderRow("Background opacity", motion.face_alpha ?? 255, 0, 255, 1, (value) => {
          motion.face_alpha = Math.round(value);
        })
      );
      genericPanel.appendChild(
        sliderRow("Rim thickness", motion.rim_width ?? 0.09, 0.01, 0.3, 0.005, (value) => {
          motion.rim_width = value;
        })
      );
    }
    const tickFields = [["Tick count", "tick_count", 11]];
    if (state.gaugeAdvanced) tickFields.push(["Major tick every", "major_tick_every", 5]);
    for (const [label, key, fallback] of tickFields) {
      const tickRow = row(label);
      tickRow.appendChild(
        numberInput(motion[key] ?? fallback, (value) => {
          motion[key] = Math.max(key === "tick_count" ? 2 : 1, Math.round(value));
          onMotionChanged();
        }, "1")
      );
      genericPanel.appendChild(tickRow);
    }
    if (state.gaugeAdvanced) {
      genericPanel.appendChild(
        sliderRow("Tick length", motion.tick_length ?? 0.105, 0.015, 0.3, 0.005, (value) => {
          motion.tick_length = value;
        })
      );
      genericPanel.appendChild(
        sliderRow("Tick thickness", motion.tick_width ?? 0.75, 0.25, 3, 0.05, (value) => {
          motion.tick_width = value;
        })
      );
    }
  }

  const styleHeading = document.createElement("h2");
  styleHeading.textContent = "Needle material";
  genericPanel.appendChild(styleHeading);
  const needleColors = [
    ["Needle color", "needle_color", [196, 68, 49]],
    ["Pivot cap", "pivot_color", [116, 91, 61]],
  ];
  if (state.gaugeAdvanced) needleColors.push(
    ["Dark edge", "edge_color", [67, 31, 24]],
    ["Highlight", "highlight_color", [245, 163, 118]]
  );
  for (const [label, key, fallback] of needleColors) {
    genericPanel.appendChild(
      colorRow(label, () => motion[key] || fallback, (value) => {
        motion[key] = value;
      })
    );
  }
  if (state.gaugeAdvanced) {
    genericPanel.appendChild(
      vecRow("Shadow offset (x, y px)", () => motion.shadow_offset || [0.8, 1], (value) => {
        motion.shadow_offset = value;
      })
    );
  }
  genericPanel.appendChild(
    sliderRow("Shadow strength", motion.shadow_alpha ?? 115, 0, 255, 1, (value) => {
      motion.shadow_alpha = Math.round(value);
    })
  );
  if (state.gaugeAdvanced) {
    genericPanel.appendChild(
      sliderRow("Shadow softness", motion.shadow_blur ?? 0.55, 0, 2.5, 0.05, (value) => {
        motion.shadow_blur = value;
      })
    );
  }
  genericPanel.appendChild(
    sliderRow("Gauge face size / clip", motion.face_fraction ?? 1, 0.2, 1.25, 0.01, (value) => {
      motion.face_fraction = value;
    })
  );
  if (state.gaugeAdvanced) {
    genericPanel.appendChild(
      sliderRow("Clip feather", motion.aperture_feather ?? 0.5, 0, 2, 0.01, (value) => {
        motion.aperture_feather = value;
      })
    );
    const supersampleRow = row("Supersample");
    supersampleRow.appendChild(
      numberInput(motion.supersample ?? 6, (value) => {
        motion.supersample = clamp(Math.round(value), 1, 12);
        onMotionChanged();
      }, "1")
    );
    genericPanel.appendChild(supersampleRow);
  }
}

function buildVibrationPanels(motion) {
  if (!Array.isArray(motion.pivot)) {
    motion.pivot = [
      round2(motion.polygon.reduce((sum, point) => sum + point[0], 0) / motion.polygon.length),
      round2(motion.polygon.reduce((sum, point) => sum + point[1], 0) / motion.polygon.length),
    ];
  }
  if (!Array.isArray(motion.amplitude)) motion.amplitude = [0.65, 1.0];
  const heading = document.createElement("h2");
  heading.textContent = "Precise vibrating selection";
  geometryPanel.appendChild(heading);
  const intro = document.createElement("p");
  intro.className = "muted-note";
  intro.textContent =
    "Trace only the physical piece that should move. Click a white vertex before adding to split that edge; " +
    "the blue crosshair is the rotation pivot and the blue arrow is the maximum displacement vector.";
  geometryPanel.appendChild(intro);
  shapeSection(geometryPanel, motion, getShapeSpec(motion));

  const vertexButtons = document.createElement("div");
  vertexButtons.className = "button-row";
  const addVertex = document.createElement("button");
  addVertex.textContent = "+ Split selected / longest edge";
  addVertex.addEventListener("click", () => addVibrationVertex(motion));
  const removeVertex = document.createElement("button");
  removeVertex.textContent = "− Remove selected vertex";
  removeVertex.disabled = motion.polygon.length <= 3;
  removeVertex.addEventListener("click", () => removeVibrationVertex(motion));
  vertexButtons.appendChild(addVertex);
  vertexButtons.appendChild(removeVertex);
  geometryPanel.appendChild(vertexButtons);

  geometryPanel.appendChild(
    vecRow(
      "Pivot (x, y)",
      () => motion.pivot,
      (value) => {
        motion.pivot = value;
      }
    )
  );
  geometryPanel.appendChild(
    vecRow(
      "Amplitude vector (x, y px)",
      () => motion.amplitude,
      (value) => {
        motion.amplitude = value;
      }
    )
  );
  geometryPanel.appendChild(
    sliderRow("Selection feather", motion.feather ?? 0.65, 0, 2.5, 0.01, (value) => {
      motion.feather = value;
    })
  );

  const motionHeading = document.createElement("h2");
  motionHeading.textContent = "Vibration profile";
  secondaryPanel.appendChild(motionHeading);
  const waveformRow = row("Waveform");
  const waveformSelect = document.createElement("select");
  for (const [value, label] of [
    ["motor", "motor (weighted harmonics)"],
    ["rattle", "rattle (sharper harmonics)"],
    ["sine", "sine (smooth)"],
  ]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    if ((motion.waveform ?? "motor") === value) option.selected = true;
    waveformSelect.appendChild(option);
  }
  waveformSelect.addEventListener("change", () => {
    motion.waveform = waveformSelect.value;
    onMotionChanged(true);
  });
  waveformRow.appendChild(waveformSelect);
  secondaryPanel.appendChild(waveformRow);

  const cyclesRow = row("Cycles / loop");
  cyclesRow.appendChild(
    numberInput(motion.cycles_per_loop ?? 3, (value) => {
      motion.cycles_per_loop = Math.max(1, Math.round(value));
      onMotionChanged();
    }, "1")
  );
  secondaryPanel.appendChild(cyclesRow);
  for (const [label, key, fallback, min, max, step] of [
    ["Starting phase", "phase", 0, 0, 1, 0.005],
    ["Y phase offset", "y_phase_offset", 0, 0, 1, 0.005],
    ["Micro-rotation (degrees)", "rotation_degrees", 0.25, 0, 3, 0.01],
    ["Rotation phase offset", "rotation_phase_offset", 0, 0, 1, 0.005],
  ]) {
    secondaryPanel.appendChild(
      sliderRow(label, motion[key] ?? fallback, min, max, step, (value) => {
        motion[key] = value;
      })
    );
  }
  const supersampleRow = row("Supersample");
  supersampleRow.appendChild(
    numberInput(motion.supersample ?? 6, (value) => {
      motion.supersample = Math.max(1, Math.round(value));
      onMotionChanged();
    }, "1")
  );
  secondaryPanel.appendChild(supersampleRow);
  const closureNote = document.createElement("p");
  closureNote.className = "muted-note";
  closureNote.textContent =
    "Cycles / loop is integral, so even the multi-harmonic motor and rattle profiles return exactly to their starting transform.";
  secondaryPanel.appendChild(closureNote);

  const backgroundHeading = document.createElement("h2");
  backgroundHeading.textContent = "Behind the moving piece";
  genericPanel.appendChild(backgroundHeading);
  const backgroundRow = row("Background mode");
  const backgroundSelect = document.createElement("select");
  for (const [value, label] of [
    ["source", "preserve source (best for tiny jiggle)"],
    ["dark_cavity", "dark cavity (best for separated part)"],
  ]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    if ((motion.background_mode ?? "source") === value) option.selected = true;
    backgroundSelect.appendChild(option);
  }
  backgroundSelect.addEventListener("change", () => {
    motion.background_mode = backgroundSelect.value;
    buildPanels();
    onMotionChanged(true);
  });
  backgroundRow.appendChild(backgroundSelect);
  genericPanel.appendChild(backgroundRow);
  if (motion.background_mode === "dark_cavity") {
    genericPanel.appendChild(
      sliderRow("Cavity brightness", motion.cavity_brightness ?? 0.48, 0.1, 1, 0.01, (value) => {
        motion.cavity_brightness = value;
      })
    );
    genericPanel.appendChild(
      sliderRow("Cavity blur", motion.cavity_blur ?? 1.2, 0, 4, 0.05, (value) => {
        motion.cavity_blur = value;
      })
    );
  }
  const orderNote = document.createElement("p");
  orderNote.className = "muted-note";
  orderNote.textContent =
    "This layer captures everything painted before it. Put vibration after a fan/gear to move that live animation as one part; " +
    "put stationary foreground bars after vibration so they remain fixed above it.";
  genericPanel.appendChild(orderNote);
}

function buildAssetSection() {
  if (!state.asset) {
    assetSectionEl.classList.add("hidden");
    return;
  }
  assetSectionEl.classList.remove("hidden");
  assetFrameCountEl.value = state.frameCount;
  const lighting = state.lighting;
  assetLightingEnabledEl.checked = Boolean(lighting.enabled);
  assetLightingDirectionEl.value = lighting.direction_degrees;
  assetLightingStrengthEl.value = lighting.strength;
  assetLightingAmbientEl.value = lighting.ambient;
  assetLightingStrengthValueEl.textContent = Number(lighting.strength).toFixed(2);
  assetLightingAmbientValueEl.textContent = Number(lighting.ambient).toFixed(2);
  assetSheetColumnsEl.textContent = sheetColumns(state.frameCount);
  updateSheetSizeDisplay();
}

function updateSheetSizeDisplay() {
  if (!state.asset) {
    assetSheetSizeEl.textContent = "—";
    return;
  }
  const [w, h] = state.asset.size;
  const frameCount = state.frameCount;
  const cols = sheetColumns(frameCount);
  const rows = frameCount / cols;
  const sheetW = w * cols;
  const sheetH = h * rows;
  assetSheetColumnsEl.textContent = String(cols);
  assetSheetSizeEl.textContent = `${sheetW} × ${sheetH} (${cols}×${rows})`;
}

function buildPanels() {
  const motion = state.motion;
  state.refreshCallbacks = [];
  clearChildren(geometryPanel);
  clearChildren(secondaryPanel);
  clearChildren(genericPanel);
  clearChildren(commonPanel);

  if (!motion) {
    const note = document.createElement("p");
    note.className = "muted-note";
    note.textContent = "This sprite has no layers. Pick a type above and click \"+ Add layer\" to create one.";
    genericPanel.appendChild(note);
    return;
  }

  const isMechanical = motion.type === "mechanical_rotor" || motion.type === "mechanical_gear";
  const planes = isMechanical ? getPlanes(motion) : [];

  if (motion.type === "vibration") {
    buildVibrationPanels(motion);
  } else if (motion.type === "vertical_gear") {
    buildVerticalGearPanels(motion);
  } else if (motion.type === "source_occluder") {
    buildSourceOccluderPanels(motion);
  } else if (motion.type === "gauge") {
    buildGaugePanels(motion);
  } else if (motion.type === "chase") {
    buildChasePanels(motion);
  } else if (isMechanical) {
    const heading = document.createElement("h2");
    heading.textContent = motion.type === "mechanical_rotor" ? "Fan geometry" : "Cog geometry";
    geometryPanel.appendChild(heading);
    mechanicalPlaneSection(geometryPanel, motion, planes[0]);

    geometryPanel.appendChild(
      sliderRow("Aperture feather", motion.aperture_feather ?? 0.6, 0, 1.5, 0.01, (v) => {
        motion.aperture_feather = v;
      })
    );

    const countKey = motion.type === "mechanical_rotor" ? "blade_count" : "tooth_count";
    const countLabel = motion.type === "mechanical_rotor" ? "Blade count" : "Tooth count";
    geometryPanel.appendChild(
      (() => {
        const wrap = row(countLabel);
        const input = numberInput(motion[countKey] ?? 8, (v) => {
          motion[countKey] = Math.max(3, Math.round(v));
          onMotionChanged();
        }, "1");
        wrap.appendChild(input);
        return wrap;
      })()
    );

    geometryPanel.appendChild(
      (() => {
        const wrap = row("Base angle (rad)");
        const input = numberInput(motion.base_angle ?? 0, (v) => {
          motion.base_angle = v;
          onMotionChanged();
        }, "0.01");
        wrap.appendChild(input);
        const degrees = document.createElement("span");
        degrees.className = "value";
        degrees.textContent = ((motion.base_angle ?? 0) * (180 / Math.PI)).toFixed(1) + "°";
        input.addEventListener("input", () => {
          degrees.textContent = (parseFloat(input.value || "0") * (180 / Math.PI)).toFixed(1) + "°";
        });
        wrap.appendChild(degrees);
        return wrap;
      })()
    );

    geometryPanel.appendChild(
      (() => {
        const wrap = row("Direction");
        const select = document.createElement("select");
        for (const value of [-1, 1]) {
          const option = document.createElement("option");
          option.value = String(value);
          option.textContent = value === -1 ? "-1 (clockwise)" : "1 (counter-clockwise)";
          if ((motion.direction ?? -1) === value) option.selected = true;
          select.appendChild(option);
        }
        select.addEventListener("change", () => {
          motion.direction = parseFloat(select.value);
          onMotionChanged();
        });
        wrap.appendChild(select);
        return wrap;
      })()
    );

    geometryPanel.appendChild(
      (() => {
        const wrap = row("Supersample");
        const input = numberInput(motion.supersample ?? 8, (v) => {
          motion.supersample = Math.max(1, Math.round(v));
          onMotionChanged();
        }, "1");
        wrap.appendChild(input);
        return wrap;
      })()
    );

    geometryPanel.appendChild(
      (() => {
        const wrap = row("Pitches / loop");
        const input = numberInput(motion.pitches_per_loop ?? 1, (v) => {
          motion.pitches_per_loop = Math.max(1, Math.round(v));
          onMotionChanged();
        }, "1");
        wrap.appendChild(input);
        return wrap;
      })()
    );
    const speedNote = document.createElement("p");
    speedNote.className = "muted-note";
    speedNote.textContent =
      "Rotation speed: how many blade/tooth pitches this layer advances over the configured frame loop. " +
      "Must be a whole number to keep the loop seamless -- higher looks faster.";
    geometryPanel.appendChild(speedNote);

    if (motion.type === "mechanical_gear") {
      buildMechanicalGearConstructionSection(secondaryPanel, motion);
      buildGearCenterFillSection(secondaryPanel, motion);
      buildGearColorSection(genericPanel, motion);
    } else if (planes.length > 1) {
      fillRatioSection(secondaryPanel, motion, planes[1], planes[0], { featherKey: "hub_feather" });
    }
  } else {
    const shape = getShapeSpec(motion);
    if (shape) {
      const heading = document.createElement("h2");
      heading.textContent = "Position / shape";
      genericPanel.appendChild(heading);
      shapeSection(genericPanel, motion, shape);
    } else {
      const note = document.createElement("p");
      note.className = "muted-note";
      note.textContent = "No position field recognised on this motion. Edit it directly with the raw JSON panel below.";
      genericPanel.appendChild(note);
    }
    if (motion.type === "sweep") buildSweepCircleSection(genericPanel, motion);
    buildMaskSection(genericPanel, motion);
  }

  if (
    motion.type !== "vertical_gear" &&
    motion.type !== "vibration" &&
    motion.type !== "source_occluder" &&
    motion.type !== "gauge"
  ) {
    buildCommonPanel(commonPanel, motion);
  } else {
    buildLayerLightingSection(commonPanel, motion);
  }
}

// --------------------------------------------------------------- raw json

function syncRawJson() {
  if (document.activeElement !== rawJsonEl) {
    rawJsonEl.value = JSON.stringify(state.motion, null, 2);
  }
}

el("apply-json").addEventListener("click", () => {
  if (state.motionIndex < 0) return;
  try {
    const parsed = JSON.parse(rawJsonEl.value);
    if (!parsed.type) throw new Error('motion must include a "type" field');
    state.motion = parsed;
    state.workingMotions[state.motionIndex] = parsed;
    jsonErrorEl.textContent = "";
    buildPanels();
    onMotionChanged(true);
  } catch (error) {
    jsonErrorEl.textContent = error.message;
  }
});

el("format-json").addEventListener("click", () => {
  try {
    const parsed = JSON.parse(rawJsonEl.value);
    rawJsonEl.value = JSON.stringify(parsed, null, 2);
    jsonErrorEl.textContent = "";
  } catch (error) {
    jsonErrorEl.textContent = error.message;
  }
});

// -------------------------------------------------------------- rendering

let renderTimer = null;

function onMotionChanged(immediate) {
  syncRawJson();
  scheduleRender(Boolean(immediate));
  updateDirtyIndicator();
}

function scheduleRender(immediate) {
  clearTimeout(renderTimer);
  renderTimer = setTimeout(doRender, immediate ? 0 : 150);
}

async function doRender() {
  if (!state.asset) return;
  const seq = ++state.requestSeq;

  if (!state.motion) {
    // No layers on this sprite -- just show the plain source sprite.
    setStatus("Rendering…");
    try {
      const blob = await api.getSourceImage();
      const url = URL.createObjectURL(blob);
      const image = new Image();
      await new Promise((resolve) => {
        image.onload = resolve;
        image.src = url;
      });
      if (seq !== state.requestSeq) return;
      state.frameImages = [image];
      setStatus("Ready (no layers)", "ok");
    } catch (error) {
      setStatus("Request failed: " + error.message, "error");
    }
    return;
  }

  setStatus("Rendering…");
  let payload;
  try {
    payload = await api.preview({
      motions: state.workingMotions,
      selected_index: state.motionIndex,
      frame_count: state.frameCount,
      isolate: isolateToggle.checked,
      lighting: state.lighting,
    });
  } catch (error) {
    setStatus("Render failed: " + error.message, "error");
    return;
  }
  if (seq !== state.requestSeq) return; // superseded by a newer edit
  const images = await Promise.all(
    payload.frames.map(
      (b64) =>
        new Promise((resolve) => {
          const image = new Image();
          image.onload = () => resolve(image);
          image.src = "data:image/png;base64," + b64;
        })
    )
  );
  if (seq !== state.requestSeq) return;
  state.frameImages = images;
  setStatus("Ready", "ok");
}

// ------------------------------------------------------------ open/browse
//
// A server-backed directory browser (not a plain <input type="file">) --
// the picked path is used to bake sprite sheets back to disk server-side,
// and browsers don't expose a real filesystem path from a file input.

const browseOverlay = el("browse-overlay");
const browseTitle = el("browse-title");
const browsePathEl = el("browse-path");
const browseList = el("browse-list");
const browseUpBtn = el("browse-up");
const browseErrorEl = el("browse-error");

const browseState = { kind: "json", dir: null, parent: null, onSelect: null, lastDir: {} };

async function browseTo(dir) {
  browseErrorEl.textContent = "";
  let payload;
  try {
    payload = await api.browse(browseState.kind, dir);
  } catch (error) {
    browseErrorEl.textContent = error.message;
    return;
  }
  browseState.dir = payload.path;
  browseState.parent = payload.parent;
  browseState.lastDir[browseState.kind] = payload.path;
  browsePathEl.textContent = payload.path;
  browsePathEl.title = payload.path;
  browseUpBtn.disabled = !payload.parent;
  browseList.innerHTML = "";
  for (const entry of payload.entries) {
    const row = document.createElement("div");
    row.className = "browse-entry" + (entry.is_dir ? " dir" : "");
    row.textContent = (entry.is_dir ? "\u{1F4C1} " : "\u{1F4C4} ") + entry.name;
    row.addEventListener("click", () => {
      if (entry.is_dir) browseTo(entry.path);
      else selectBrowseFile(entry.path);
    });
    browseList.appendChild(row);
  }
}

function selectBrowseFile(path) {
  const onSelect = browseState.onSelect;
  closeBrowseModal();
  if (onSelect) onSelect(path);
}

function openBrowseModal({ kind, title, onSelect }) {
  browseState.kind = kind;
  browseState.onSelect = onSelect;
  browseTitle.textContent = title;
  browseOverlay.classList.remove("hidden");
  browseTo(browseState.lastDir[kind] || null);
}

function closeBrowseModal() {
  browseOverlay.classList.add("hidden");
}

el("browse-close").addEventListener("click", closeBrowseModal);
browseOverlay.addEventListener("click", (event) => {
  if (event.target === browseOverlay) closeBrowseModal();
});
browseUpBtn.addEventListener("click", () => {
  if (browseState.parent) browseTo(browseState.parent);
});

// --------------------------------------------------------------- open asset

async function confirmDiscardIfNeeded() {
  if (!state.asset || !hasUnsavedChanges()) return true;
  return confirm(`Discard unsaved layer changes on "${state.asset.name}"?\n\nClick Cancel to stay and save first.`);
}

async function openAssetFile(path) {
  if (!(await confirmDiscardIfNeeded())) return;
  setStatus("Opening…");
  let payload;
  try {
    payload = await api.openAssetFile(path);
  } catch (error) {
    setStatus("Open failed: " + error.message, "error");
    return;
  }
  applyOpenedAsset(payload.asset, payload.path);
  setStatus(`Opened "${payload.asset.name}"`, "ok");
}

el("open-asset-btn").addEventListener("click", () => {
  openBrowseModal({
    kind: "json",
    title: "Open asset",
    onSelect: (path) => openAssetFile(path),
  });
});

el("welcome-open-btn").addEventListener("click", () => el("open-asset-btn").click());

async function openAssetFromImage(sourcePath) {
  if (!(await confirmDiscardIfNeeded())) return;
  setStatus("Opening image…");
  let payload;
  try {
    payload = await api.openAssetFromImage({ source_path: sourcePath });
  } catch (error) {
    setStatus("Open failed: " + error.message, "error");
    return;
  }
  if (payload.needs_details) {
    openNewAssetModal(sourcePath);
    return;
  }
  applyOpenedAsset(payload.asset, payload.path);
  setStatus(`Opened "${payload.asset.name}"`, "ok");
}

el("new-asset-btn").addEventListener("click", async () => {
  if (!(await confirmDiscardIfNeeded())) return;
  openBrowseModal({
    kind: "image",
    title: "New asset from image",
    onSelect: (path) => openAssetFromImage(path),
  });
});

el("welcome-new-btn").addEventListener("click", () => el("new-asset-btn").click());

// ---------------------------------------------------------- new asset modal

const newAssetOverlay = el("new-asset-overlay");
const newAssetSourceLabel = el("new-asset-source-label");
const newAssetNameInput = el("new-asset-name");
const newAssetOutputInput = el("new-asset-output");
const newAssetErrorEl = el("new-asset-error");
let pendingNewAssetSource = null;

function openNewAssetModal(sourcePath) {
  pendingNewAssetSource = sourcePath;
  newAssetErrorEl.textContent = "";
  newAssetSourceLabel.textContent = "Source: " + sourcePath;
  const base = baseNameNoExt(sourcePath);
  newAssetNameInput.value = base;
  newAssetOutputInput.value = pathDirname(sourcePath) + "/" + base + "-animation.png";
  newAssetOverlay.classList.remove("hidden");
}

function closeNewAssetModal() {
  newAssetOverlay.classList.add("hidden");
  pendingNewAssetSource = null;
}

el("new-asset-close").addEventListener("click", closeNewAssetModal);
el("new-asset-cancel").addEventListener("click", closeNewAssetModal);
newAssetOverlay.addEventListener("click", (event) => {
  if (event.target === newAssetOverlay) closeNewAssetModal();
});

el("new-asset-confirm").addEventListener("click", async () => {
  const name = newAssetNameInput.value.trim();
  const outputPath = newAssetOutputInput.value.trim();
  if (!name || !outputPath) {
    newAssetErrorEl.textContent = "Name and output path are required.";
    return;
  }
  let payload;
  try {
    payload = await api.openAssetFromImage({
      source_path: pendingNewAssetSource,
      name,
      output_path: outputPath,
    });
  } catch (error) {
    newAssetErrorEl.textContent = error.message;
    return;
  }
  newAssetOverlay.classList.add("hidden");
  pendingNewAssetSource = null;
  applyOpenedAsset(payload.asset, payload.path);
  setStatus(`Created asset "${payload.asset.name}"`, "ok");
});

// --------------------------------------------------------------- controls

window.addEventListener("beforeunload", (event) => {
  if (!hasUnsavedChanges()) return;
  event.preventDefault();
  event.returnValue = "";
});

isolateToggle.addEventListener("change", () => scheduleRender(true));
animationSpeedInput.addEventListener("input", () => {
  const value = parseFloat(animationSpeedInput.value);
  if (!Number.isFinite(value) || value <= 0) return;
  state.animationSpeed = value;
  updateAnimationSpeedNote();
  updateDirtyIndicator();
});

assetFrameCountEl.addEventListener("input", () => {
  const value = Number(assetFrameCountEl.value);
  if (!validFrameCount(value)) {
    assetFrameCountEl.setCustomValidity("Choose a non-prime whole number from 1 to 64.");
    return;
  }
  assetFrameCountEl.setCustomValidity("");
  state.frameCount = value;
  updateAnimationSpeedNote();
  updateSheetSizeDisplay();
  updateDirtyIndicator();
  scheduleRender(true);
});

assetFrameCountEl.addEventListener("change", () => {
  const value = Number(assetFrameCountEl.value);
  if (!validFrameCount(value)) {
    assetFrameCountEl.value = state.frameCount;
    assetFrameCountEl.setCustomValidity("");
    setStatus("Frame count must be a non-prime whole number from 1 to 64.", "error");
    return;
  }
  assetFrameCountEl.setCustomValidity("");
});

assetLightingEnabledEl.addEventListener("change", () => {
  state.lighting.enabled = assetLightingEnabledEl.checked;
  updateDirtyIndicator();
  scheduleRender(true);
});

assetLightingDirectionEl.addEventListener("input", () => {
  const value = Number(assetLightingDirectionEl.value);
  if (!Number.isFinite(value)) return;
  state.lighting.direction_degrees = clamp(value, 0, 360);
  updateDirtyIndicator();
  scheduleRender(true);
});

for (const [input, valueEl, key] of [
  [assetLightingStrengthEl, assetLightingStrengthValueEl, "strength"],
  [assetLightingAmbientEl, assetLightingAmbientValueEl, "ambient"],
]) {
  input.addEventListener("input", () => {
    const value = Number(input.value);
    state.lighting[key] = value;
    valueEl.textContent = value.toFixed(2);
    updateDirtyIndicator();
    scheduleRender(true);
  });
}

playToggle.addEventListener("click", () => {
  state.playing = !state.playing;
  playToggle.textContent = state.playing ? "Pause" : "Play";
});

el("zoom-in").addEventListener("click", () => {
  state.zoom = clamp(state.zoom + 0.25, 0.25, 8);
  updateZoomLabel();
  resizeCanvas();
});
el("zoom-out").addEventListener("click", () => {
  state.zoom = clamp(state.zoom - 0.25, 0.25, 8);
  updateZoomLabel();
  resizeCanvas();
});
el("zoom-reset").addEventListener("click", () => {
  state.zoom = 1;
  updateZoomLabel();
  resizeCanvas();
});
function updateZoomLabel() {
  zoomLabel.textContent = (state.baseScale * state.zoom).toFixed(1) + "x";
}

addLayerBtn.addEventListener("click", () => addLayer());

el("save-btn").addEventListener("click", async () => {
  await saveAsset();
});

el("regenerate-btn").addEventListener("click", async () => {
  const saved = await saveAsset();
  if (!saved) return;
  setStatus("Regenerating sheet…");
  let payload;
  try {
    payload = await api.regenerate();
  } catch (error) {
    setStatus("Generate failed: " + error.message, "error");
    return;
  }
  const record = payload.record;
  setStatus(
    `Regenerated ${record.name}: identity≥${record.minimum_identity_ratio.toFixed(3)}, ` +
      `seam ${record.loop_seam_step_ratio.toFixed(2)}x step`,
    "ok"
  );
});

el("export-gif-btn").addEventListener("click", async () => {
  await exportGif();
});

el("reload-btn").addEventListener("click", async () => {
  if (!confirm("Discard unsaved edits and reload the current JSON from disk?")) return;
  let payload;
  try {
    payload = await api.reload();
  } catch (error) {
    setStatus("Reload failed: " + error.message, "error");
    return;
  }
  applyOpenedAsset(payload.asset, payload.path);
  setStatus("Reloaded from disk", "ok");
});

async function exportGif() {
  if (!state.asset) {
    setStatus('No asset open -- click "Open…" first', "error");
    return;
  }
  const btn = el("export-gif-btn");
  btn.disabled = true;
  setStatus("Exporting GIF…");
  try {
    const payload = await api.exportGif({
      motions: state.workingMotions,
      selected_index: state.motionIndex >= 0 ? state.motionIndex : 0,
      isolate: isolateToggle.checked,
      animation_speed: state.animationSpeed,
      frame_count: state.frameCount,
      lighting: state.lighting,
    });
    const a = document.createElement("a");
    a.href = "data:image/gif;base64," + payload.gif;
    a.download = payload.filename || (state.asset.name + ".gif");
    document.body.appendChild(a);
    a.click();
    a.remove();
    setStatus(`Exported ${payload.filename} (${payload.frame_count} frames, ${payload.duration_ms}ms)`, "ok");
  } catch (error) {
    setStatus("GIF export failed: " + error.message, "error");
  } finally {
    btn.disabled = false;
  }
}

async function saveAsset() {
  if (!state.asset) {
    setStatus('No asset open -- click "Open…" first', "error");
    return false;
  }
  setStatus("Saving…");
  let payload;
  try {
    payload = await api.save({
      motions: state.workingMotions,
      animation_speed: state.animationSpeed,
      frame_count: state.frameCount,
      lighting: state.lighting,
    });
  } catch (error) {
    setStatus("Save failed: " + error.message, "error");
    return false;
  }
  state.asset.motions = JSON.parse(JSON.stringify(state.workingMotions));
  state.asset.animation_speed = state.animationSpeed;
  state.asset.frame_count = state.frameCount;
  state.asset.lighting = JSON.parse(JSON.stringify(state.lighting));
  updateDirtyIndicator();
  setStatus(payload.warning ? payload.warning : "Saved all layers", payload.warning ? "error" : "ok");
  return true;
}

// --------------------------------------------------------------------- go

(async function init() {
  try {
    const payload = await api.getAsset();
    if (payload.asset) {
      applyOpenedAsset(payload.asset, payload.path);
      setStatus(`Opened "${payload.asset.name}"`, "ok");
    } else {
      clearAssetView();
    }
  } catch (error) {
    clearAssetView();
    setStatus(error.message, "error");
  }
})();

// The hero's signature effect: a vertical WebGL lightning bolt (ported from the original prototype).
// Renders at reduced resolution, pauses off-screen / in background tabs, and draws one still frame
// when the visitor prefers reduced motion. Falls back to a CSS bolt when WebGL is unavailable.
const VERT = "attribute vec2 aPosition; void main(){ gl_Position = vec4(aPosition, 0.0, 1.0); }";
const FRAG = `
precision mediump float;
uniform vec2 iResolution; uniform float iTime; uniform float uHue; uniform float uSpeed; uniform float uIntensity; uniform float uSize; uniform float uXOffset;
#define OCTAVES 6
vec3 hsv2rgb(vec3 c){ vec3 rgb = clamp(abs(mod(c.x*6.0+vec3(0.0,4.0,2.0),6.0)-3.0)-1.0,0.0,1.0); return c.z*mix(vec3(1.0),rgb,c.y); }
float hash11(float p){ p = fract(p*.1031); p *= p+33.33; p *= p+p; return fract(p); }
float hash12(vec2 p){ vec3 p3 = fract(vec3(p.xyx)*.1031); p3 += dot(p3,p3.yzx+33.33); return fract((p3.x+p3.y)*p3.z); }
mat2 rot(float t){ float c=cos(t), s=sin(t); return mat2(c,-s,s,c); }
float noise(vec2 p){ vec2 i=floor(p), f=fract(p); float a=hash12(i), b=hash12(i+vec2(1.,0.)), c=hash12(i+vec2(0.,1.)), d=hash12(i+vec2(1.,1.)); vec2 t=smoothstep(0.,1.,f); return mix(mix(a,b,t.x),mix(c,d,t.x),t.y); }
float fbm(vec2 p){ float v=0.0, a=0.5; for(int i=0;i<OCTAVES;++i){ v+=a*noise(p); p*=rot(0.45); p*=2.0; a*=0.5; } return v; }
void main(){
  vec2 uv = gl_FragCoord.xy/iResolution.xy; uv = 2.0*uv-1.0; uv.x *= iResolution.x/iResolution.y; uv.x += uXOffset;
  float time = iTime*uSpeed;
  uv += 1.5*fbm(uv*uSize+0.8*time)-0.75;
  float dist = abs(uv.x);
  vec3 base = hsv2rgb(vec3(uHue/360.0,0.9,0.5));
  float flicker = mix(0.0,0.08,hash11(time));
  vec3 col = base*(flicker/max(dist,0.0015))*uIntensity;
  float alpha = smoothstep(0.0,1.0,length(col));
  gl_FragColor = vec4(col, alpha*0.6);
}`;

export function startLightning(canvas, { reducedMotion = false } = {}) {
  const gl = canvas.getContext("webgl", { antialias: false, alpha: true, premultipliedAlpha: false, powerPreference: "low-power" });
  if (!gl) { document.documentElement.classList.add("no-webgl"); return null; }

  const compile = (type, src) => {
    const sh = gl.createShader(type);
    gl.shaderSource(sh, src);
    gl.compileShader(sh);
    return gl.getShaderParameter(sh, gl.COMPILE_STATUS) ? sh : null;
  };
  const vs = compile(gl.VERTEX_SHADER, VERT);
  const fs = compile(gl.FRAGMENT_SHADER, FRAG);
  if (!vs || !fs) { document.documentElement.classList.add("no-webgl"); return null; }
  const program = gl.createProgram();
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) { document.documentElement.classList.add("no-webgl"); return null; }
  gl.useProgram(program);

  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
  const pos = gl.getAttribLocation(program, "aPosition");
  gl.enableVertexAttribArray(pos);
  gl.vertexAttribPointer(pos, 2, gl.FLOAT, false, 0, 0);
  const u = Object.fromEntries(["iResolution", "iTime", "uHue", "uSpeed", "uIntensity", "uSize", "uXOffset"].map((n) => [n, gl.getUniformLocation(program, n)]));

  const hue = Number(canvas.dataset.hue) || 343;
  const speed = Number(canvas.dataset.speed) || 0.8;
  const intensity = Number(canvas.dataset.intensity) || 0.75;
  const scale = 0.5; // render at half resolution: the effect is soft, so this is invisible but ~4x cheaper

  function resize() {
    const w = Math.max(2, Math.floor(canvas.clientWidth * scale));
    const h = Math.max(2, Math.floor(canvas.clientHeight * scale));
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    gl.viewport(0, 0, canvas.width, canvas.height);
  }

  const t0 = performance.now();
  let offset = 0;
  let offsetTarget = 0;
  let strikeLevel = 0;
  let last = t0;
  function draw(now = performance.now()) {
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    offset += (offsetTarget - offset) * Math.min(1, dt * 3.2); // eases toward the pointer
    strikeLevel = Math.max(0, strikeLevel - dt * 1.3);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.uniform2f(u.iResolution, canvas.width, canvas.height);
    gl.uniform1f(u.iTime, reducedMotion ? 4.2 : (now - t0) / 1000);
    gl.uniform1f(u.uHue, hue);
    gl.uniform1f(u.uSpeed, speed);
    gl.uniform1f(u.uIntensity, intensity * (1 + strikeLevel * 2.4));
    gl.uniform1f(u.uSize, 1.0);
    gl.uniform1f(u.uXOffset, offset);
    gl.drawArrays(gl.TRIANGLES, 0, 6);
  }

  let raf = 0;
  let visible = true;
  const loop = (now) => { draw(now); raf = requestAnimationFrame(loop); };
  const run = () => { if (!raf && visible && !document.hidden && !reducedMotion) raf = requestAnimationFrame(loop); };
  const stop = () => { cancelAnimationFrame(raf); raf = 0; };

  resize();
  draw();
  window.addEventListener("resize", () => { resize(); if (!raf) draw(); });
  document.addEventListener("visibilitychange", () => (document.hidden ? stop() : run()));
  new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; visible ? run() : stop(); }).observe(canvas);

  if (!reducedMotion) {
    // The bolt leans toward your cursor or finger.
    window.addEventListener("pointermove", (e) => {
      if (!visible) return;
      const n = (e.clientX / window.innerWidth) * 2 - 1;
      offsetTarget = -n * (canvas.clientWidth / canvas.clientHeight) * 0.6;
    }, { passive: true });
    document.addEventListener("pointerleave", () => { offsetTarget = 0; });
    window.addEventListener("iron:strike", () => { strikeLevel = 1; });
  }
  run();
  return { stop, run };
}

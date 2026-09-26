// Post-processing on the GPU (WebGL2).
//
// The scene is drawn with Canvas 2D. Each output frame averages several
// sub-frames in a float buffer, in linear light (real motion blur, 180° shutter),
// then adds bloom, a touch of chromatic aberration, vignette and optional grain,
// and dithers on the way back to 8 bits so the dark gradients don't band.

const VERT = `#version 300 es
const vec2 P[3] = vec2[3](vec2(-1.0, -1.0), vec2(3.0, -1.0), vec2(-1.0, 3.0));
out vec2 uv;
void main() { vec2 p = P[gl_VertexID]; uv = p * 0.5 + 0.5; gl_Position = vec4(p, 0.0, 1.0); }`;

const ACCUMULATE = `#version 300 es
precision highp float;
uniform sampler2D src; uniform float weight;
in vec2 uv; out vec4 o;
void main() { o = vec4(texture(src, uv).rgb * weight, 1.0); }`;

// 13-tap downsample (Jimenez, "Next generation post processing in Call of Duty").
// The first pass also keeps only what is bright enough to glow (soft knee).
const DOWN = `#version 300 es
precision highp float;
uniform sampler2D src; uniform vec2 texel; uniform float threshold; uniform float knee; uniform int first;
in vec2 uv; out vec4 o;
vec3 s(vec2 d) { return texture(src, uv + d * texel).rgb; }
void main() {
  vec3 a = s(vec2(-2, 2)), b = s(vec2(0, 2)), c = s(vec2(2, 2));
  vec3 d = s(vec2(-2, 0)), e = s(vec2(0, 0)), f = s(vec2(2, 0));
  vec3 g = s(vec2(-2, -2)), h = s(vec2(0, -2)), i = s(vec2(2, -2));
  vec3 j = s(vec2(-1, 1)), k = s(vec2(1, 1)), l = s(vec2(-1, -1)), m = s(vec2(1, -1));
  vec3 col = e * 0.125 + (a + c + g + i) * 0.03125 + (b + d + f + h) * 0.0625 + (j + k + l + m) * 0.125;
  if (first == 1) {
    float br = max(col.r, max(col.g, col.b));
    float rq = clamp(br - threshold + knee, 0.0, 2.0 * knee);
    rq = rq * rq / (4.0 * knee + 1e-4);
    col *= max(rq, br - threshold) / max(br, 1e-4);
  }
  o = vec4(col, 1.0);
}`;

// 3x3 tent upsample, blended additively into the next larger level.
const UP = `#version 300 es
precision highp float;
uniform sampler2D src; uniform vec2 texel; uniform float radius;
in vec2 uv; out vec4 o;
vec3 s(vec2 d) { return texture(src, uv + d * texel * radius).rgb; }
void main() {
  vec3 col = s(vec2(0, 0)) * 4.0
    + (s(vec2(-1, 0)) + s(vec2(1, 0)) + s(vec2(0, -1)) + s(vec2(0, 1))) * 2.0
    + s(vec2(-1, -1)) + s(vec2(1, -1)) + s(vec2(-1, 1)) + s(vec2(1, 1));
  o = vec4(col / 16.0, 1.0);
}`;

const FINAL = `#version 300 es
precision highp float;
uniform sampler2D accum; uniform sampler2D bloom;
uniform vec2 res; uniform float bloomK; uniform float aberration; uniform float vignette;
uniform float grain; uniform float seed; uniform float exposure; uniform float flash;
in vec2 uv; out vec4 o;

float hash(vec3 p) {
  p = fract(p * vec3(443.897, 441.423, 437.195));
  p += dot(p, p.yzx + 19.19);
  return fract((p.x + p.y) * p.z);
}
vec3 toSrgb(vec3 c) {
  c = clamp(c, 0.0, 1.0);
  return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(0.0031308, c));
}
void main() {
  // Radial colour fringing, in pixels at the corners, growing with the square of the radius.
  vec2 d = uv - 0.5;
  float r = length(d) / 0.7071;
  vec2 off = d / max(length(d), 1e-5) * r * r * aberration / res;
  vec3 col = vec3(texture(accum, uv - off).r, texture(accum, uv).g, texture(accum, uv + off).b);
  col += texture(bloom, uv).rgb * bloomK;
  col = col * exposure + flash;
  // Soft shoulder instead of a hard clip, only on the brightest values.
  vec3 over = max(col - 0.8, 0.0);
  col = min(col, 0.8) + over / (1.0 + over * 2.5);
  float v = length(d * vec2(1.0, 0.82));
  col *= mix(1.0, smoothstep(0.95, 0.25, v), vignette);
  vec3 c = toSrgb(col);
  float luma = dot(c, vec3(0.2126, 0.7152, 0.0722));
  float n = hash(vec3(gl_FragCoord.xy, seed)) + hash(vec3(gl_FragCoord.xy + 17.0, seed + 3.1)) - 1.0;
  c += n * grain * (1.0 - 0.6 * luma);
  c += (hash(vec3(gl_FragCoord.xy, seed + 9.7)) - hash(vec3(gl_FragCoord.yx, seed + 4.3))) / 255.0;
  o = vec4(c, 1.0);
}`;

class Post {
  constructor(canvas, width, height) {
    const gl = canvas.getContext('webgl2', {
      alpha: false, antialias: false, depth: false, stencil: false, preserveDrawingBuffer: true,
    });
    if (!gl) throw new Error('WebGL2 is required');
    if (!gl.getExtension('EXT_color_buffer_float')) throw new Error('EXT_color_buffer_float is required');
    gl.getExtension('OES_texture_float_linear');
    this.gl = gl;
    this.w = width;
    this.h = height;
    this.programs = {
      accumulate: this.program(ACCUMULATE),
      down: this.program(DOWN),
      up: this.program(UP),
      final: this.program(FINAL),
    };
    this.vao = gl.createVertexArray();

    // The 2D canvas is uploaded as sRGB, so sampling returns linear light.
    this.scene = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, this.scene);
    gl.texStorage2D(gl.TEXTURE_2D, 1, gl.SRGB8_ALPHA8, width, height);
    this.filtering(gl.LINEAR);

    this.accum = this.target(width, height);
    this.mips = [];
    let w = width, h = height;
    for (let i = 0; i < 6; i++) {
      w = Math.max(1, Math.round(w / 2));
      h = Math.max(1, Math.round(h / 2));
      this.mips.push(this.target(w, h));
    }
  }

  program(fragment) {
    const gl = this.gl;
    const compile = (type, source) => {
      const s = gl.createShader(type);
      gl.shaderSource(s, source);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
      return s;
    };
    const p = gl.createProgram();
    gl.attachShader(p, compile(gl.VERTEX_SHADER, VERT));
    gl.attachShader(p, compile(gl.FRAGMENT_SHADER, fragment));
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
    const uniforms = {};
    const count = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS);
    for (let i = 0; i < count; i++) {
      const name = gl.getActiveUniform(p, i).name;
      uniforms[name] = gl.getUniformLocation(p, name);
    }
    return { p, uniforms };
  }

  filtering(mode) {
    const gl = this.gl;
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, mode);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, mode);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  }

  target(w, h) {
    const gl = this.gl;
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texStorage2D(gl.TEXTURE_2D, 1, gl.RGBA16F, w, h);
    this.filtering(gl.LINEAR);
    const fb = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
    return { tex, fb, w, h };
  }

  use(name, values, textures = []) {
    const gl = this.gl;
    const { p, uniforms } = this.programs[name];
    gl.useProgram(p);
    textures.forEach(([uniform, tex], unit) => {
      gl.activeTexture(gl.TEXTURE0 + unit);
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.uniform1i(uniforms[uniform], unit);
    });
    for (const [k, v] of Object.entries(values)) {
      if (!(k in uniforms)) continue;
      if (Array.isArray(v)) gl.uniform2f(uniforms[k], v[0], v[1]);
      else if (Number.isInteger(v) && k === 'first') gl.uniform1i(uniforms[k], v);
      else gl.uniform1f(uniforms[k], v);
    }
  }

  draw(target) {
    const gl = this.gl;
    gl.bindFramebuffer(gl.FRAMEBUFFER, target ? target.fb : null);
    gl.viewport(0, 0, target ? target.w : this.w, target ? target.h : this.h);
    gl.bindVertexArray(this.vao);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  begin() {
    const gl = this.gl;
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.accum.fb);
    gl.clearColor(0, 0, 0, 1);
    gl.clear(gl.COLOR_BUFFER_BIT);
  }

  add(source, weight) {
    const gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, this.scene);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
    gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, gl.RGBA, gl.UNSIGNED_BYTE, source);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE);
    this.use('accumulate', { weight }, [['src', this.scene]]);
    this.draw(this.accum);
    gl.disable(gl.BLEND);
  }

  finish(fx) {
    const gl = this.gl;
    let src = this.accum;
    this.mips.forEach((mip, i) => {
      this.use('down', { texel: [1 / src.w, 1 / src.h], threshold: fx.threshold, knee: fx.knee, first: i === 0 ? 1 : 0 },
        [['src', src.tex]]);
      this.draw(mip);
      src = mip;
    });
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE);
    for (let i = this.mips.length - 1; i > 0; i--) {
      const from = this.mips[i];
      this.use('up', { texel: [1 / from.w, 1 / from.h], radius: fx.radius }, [['src', from.tex]]);
      this.draw(this.mips[i - 1]);
    }
    gl.disable(gl.BLEND);
    this.use('final', {
      res: [this.w, this.h], bloomK: fx.bloom, aberration: fx.aberration, vignette: fx.vignette,
      grain: fx.grain, seed: fx.seed, exposure: fx.exposure, flash: fx.flash,
    }, [['accum', this.accum.tex], ['bloom', this.mips[0].tex]]);
    this.draw(null);
  }
}
window.Post = Post;

/* CardFind - find the cards in a photo of a lot, and cut each one out square.
 *
 * The matcher (CardHash) is a dHash: it squashes whatever rectangle you hand it
 * into 17x16 and compares adjacent pixels. That makes it fast and set-agnostic,
 * but it is NOT rotation invariant and it is very sensitive to framing -- a card
 * photographed at 15 degrees, or cropped with tablecloth around it, hashes to
 * something unrelated. LotScanner worked around that by assuming the cards sit
 * in one of seven uniform grids and slicing the image into equal cells, which
 * holds for a binder page and falls apart for anything photographed on a table.
 *
 * So this module does the part that was missing: locate each card's quadrilateral
 * and undo its rotation and perspective, so CardHash gets what it needs.
 *
 * The cheap trick that keeps this small: nothing downstream wants a
 * high-resolution deskewed card. dHash samples 17x16. So "perspective correction"
 * is about a thousand point samples through a homography, not a full image warp,
 * which is the usual reason people reach for OpenCV here.
 *
 * What it cannot do: a card that is mostly covered by another card. dHash needs
 * the whole face, so an overlapping fan is not a segmentation problem that better
 * code would solve. Those are left to the manual box editor by design.
 */
var CardFind = (function () {
  'use strict';

  var WORK = 700;            // working width; card edges survive this, and it is fast
  var RATIO = 250 / 350;     // 0.714, a card's short/long side
  var RATIO_LO = 0.56, RATIO_HI = 0.92;   // slack for perspective and sloppy edges
  var FILL_MIN = 0.72;       // blob area / its min-area rect -- a card is solid
  var AREA_LO = 0.004, AREA_HI = 0.62;    // as a fraction of the working image
  var IOU_MAX = 0.35;        // above this, two boxes are the same card

  function work(src) {
    var w = src.width, h = src.height;
    var s = Math.min(1, WORK / Math.max(w, h));
    var c = document.createElement('canvas');
    c.width = Math.max(1, Math.round(w * s));
    c.height = Math.max(1, Math.round(h * s));
    var x = c.getContext('2d', { willReadFrequently: true });
    x.imageSmoothingEnabled = true; x.imageSmoothingQuality = 'high';
    x.drawImage(src, 0, 0, c.width, c.height);
    return { cv: c, scale: c.width / w };
  }

  function luma(cv) {
    var d = cv.getContext('2d', { willReadFrequently: true })
             .getImageData(0, 0, cv.width, cv.height).data;
    var g = new Uint8Array(cv.width * cv.height);
    for (var i = 0, p = 0; p < g.length; i += 4, p++)
      g[p] = (0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]) | 0;
    return g;
  }

  /* Saturation, as a second channel to segment on.
   *
   * Brightness alone cannot find a card on a binder page, and the real photos are
   * exactly that case: a yellow-bordered Pokemon card is BRIGHT, and so is the
   * white pocket page behind it, so luma barely separates them. Measured on the
   * angled fixture, the card outline dissolved into the page and the only blobs
   * left were the darker interior features -- the detector returned 109x84 and
   * 101x74 landscape boxes, which are art boxes and text bands, not cards.
   *
   * Chroma separates them cleanly, because the thing that makes a card a card is
   * that it is colourful, and pages, sleeves, desks, carpet and daylight are not.
   * Same reasoning as running both polarities: cheaper to segment on both
   * channels than to guess which one a given photo needs. */
  function chroma(cv) {
    var d = cv.getContext('2d', { willReadFrequently: true })
             .getImageData(0, 0, cv.width, cv.height).data;
    var s = new Uint8Array(cv.width * cv.height);
    for (var i = 0, p = 0; p < s.length; i += 4, p++) {
      var r = d[i], g = d[i + 1], b = d[i + 2];
      var mx = r > g ? (r > b ? r : b) : (g > b ? g : b);
      var mn = r < g ? (r < b ? r : b) : (g < b ? g : b);
      s[p] = mx - mn;              // 0 for any grey, high for saturated colour
    }
    return s;
  }

  /* Otsu: pick the threshold that best splits the histogram in two. Chosen over a
     fixed cutoff because the same number cannot serve a dark carpet and a white
     listing page. */
  function otsu(g) {
    var hist = new Float64Array(256), i;
    for (i = 0; i < g.length; i++) hist[g[i]]++;
    var total = g.length, sum = 0;
    for (i = 0; i < 256; i++) sum += i * hist[i];
    var sumB = 0, wB = 0, best = 0, bestVar = -1;
    for (i = 0; i < 256; i++) {
      wB += hist[i]; if (!wB) continue;
      var wF = total - wB; if (!wF) break;
      sumB += i * hist[i];
      var mB = sumB / wB, mF = (sum - sumB) / wF;
      var v = wB * wF * (mB - mF) * (mB - mF);
      if (v > bestVar) { bestVar = v; best = i; }
    }
    return best;
  }

  /* Flood the mask into labelled blobs. Iterative on an explicit stack: a photo
     can be a single component of 300k pixels and recursion would blow the stack
     on exactly the biggest, most interesting blob. */
  function blobs(mask, w, h, minPx, maxPx) {
    var seen = new Uint8Array(w * h), out = [], stack = new Int32Array(w * h);
    for (var s = 0; s < w * h; s++) {
      if (seen[s] || !mask[s]) continue;
      var top = 0, n = 0, minx = w, miny = h, maxx = -1, maxy = -1;
      var pts = [];
      stack[top++] = s; seen[s] = 1;
      while (top) {
        var p = stack[--top], px = p % w, py = (p / w) | 0;
        n++;
        if (px < minx) minx = px; if (px > maxx) maxx = px;
        if (py < miny) miny = py; if (py > maxy) maxy = py;
        // Only boundary pixels are kept: the hull needs extremes, and holding
        // every interior pixel of a big blob is wasted memory.
        if (px === 0 || py === 0 || px === w - 1 || py === h - 1 ||
            !mask[p - 1] || !mask[p + 1] || !mask[p - w] || !mask[p + w])
          pts.push(px, py);
        if (px > 0 && !seen[p - 1] && mask[p - 1]) { seen[p - 1] = 1; stack[top++] = p - 1; }
        if (px < w - 1 && !seen[p + 1] && mask[p + 1]) { seen[p + 1] = 1; stack[top++] = p + 1; }
        if (py > 0 && !seen[p - w] && mask[p - w]) { seen[p - w] = 1; stack[top++] = p - w; }
        if (py < h - 1 && !seen[p + w] && mask[p + w]) { seen[p + w] = 1; stack[top++] = p + w; }
      }
      if (n >= minPx && n <= maxPx) out.push({ n: n, pts: pts });
    }
    return out;
  }

  /* Andrew's monotone chain. */
  function hull(pts) {
    var P = [], i;
    for (i = 0; i < pts.length; i += 2) P.push([pts[i], pts[i + 1]]);
    if (P.length < 3) return P;
    P.sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
    var cross = function (o, a, b) {
      return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
    };
    var lo = [], up = [];
    for (i = 0; i < P.length; i++) {
      while (lo.length >= 2 && cross(lo[lo.length - 2], lo[lo.length - 1], P[i]) <= 0) lo.pop();
      lo.push(P[i]);
    }
    for (i = P.length - 1; i >= 0; i--) {
      while (up.length >= 2 && cross(up[up.length - 2], up[up.length - 1], P[i]) <= 0) up.pop();
      up.push(P[i]);
    }
    lo.pop(); up.pop();
    return lo.concat(up);
  }

  /* Minimum-area enclosing rectangle. One side of it lies on a hull edge, so
     trying every edge is exhaustive rather than approximate; hulls here are a
     few dozen points, so the quadratic pass is nothing. */
  function minAreaRect(H) {
    if (H.length < 3) return null;
    var best = null;
    for (var i = 0; i < H.length; i++) {
      var a = H[i], b = H[(i + 1) % H.length];
      var ex = b[0] - a[0], ey = b[1] - a[1];
      var len = Math.hypot(ex, ey); if (len < 1e-6) continue;
      var ux = ex / len, uy = ey / len;
      var lo1 = Infinity, hi1 = -Infinity, lo2 = Infinity, hi2 = -Infinity;
      for (var j = 0; j < H.length; j++) {
        var dx = H[j][0] - a[0], dy = H[j][1] - a[1];
        var p1 = dx * ux + dy * uy, p2 = -dx * uy + dy * ux;
        if (p1 < lo1) lo1 = p1; if (p1 > hi1) hi1 = p1;
        if (p2 < lo2) lo2 = p2; if (p2 > hi2) hi2 = p2;
      }
      var w = hi1 - lo1, h = hi2 - lo2, area = w * h;
      if (!best || area < best.area) {
        var C = function (s, t) {
          return [a[0] + ux * s - uy * t, a[1] + uy * s + ux * t];
        };
        best = { area: area, w: w, h: h,
                 quad: [C(lo1, lo2), C(hi1, lo2), C(hi1, hi2), C(lo1, hi2)] };
      }
    }
    return best;
  }

  /* Put the corners in a predictable order: portrait, starting top-left, going
     clockwise. Note the 180-degree ambiguity is NOT resolved here -- nothing in
     the geometry says which end of a card is the top. Callers hash both ways. */
  function orient(rect) {
    var q = rect.quad, w = rect.w, h = rect.h;
    if (w > h) { q = [q[1], q[2], q[3], q[0]]; var t = w; w = h; h = t; }
    var cy = (q[0][1] + q[1][1] + q[2][1] + q[3][1]) / 4;
    var top = q.filter(function (p) { return p[1] <= cy; });
    if (top.length === 2 && top[0][0] > top[1][0]) q = [q[1], q[2], q[3], q[0]];
    return { quad: q, w: w, h: h };
  }

  /* Shoelace, any polygon -- used on hulls as well as quads. */
  function quadArea(q) {
    var s = 0, n = q.length;
    for (var i = 0; i < n; i++) {
      var a = q[i], b = q[(i + 1) % n];
      s += a[0] * b[1] - b[0] * a[1];
    }
    return Math.abs(s) / 2;
  }

  function bbox(q) {
    var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (var i = 0; i < 4; i++) {
      if (q[i][0] < x0) x0 = q[i][0]; if (q[i][0] > x1) x1 = q[i][0];
      if (q[i][1] < y0) y0 = q[i][1]; if (q[i][1] > y1) y1 = q[i][1];
    }
    return [x0, y0, x1, y1];
  }

  function iou(a, b) {
    var A = bbox(a), B = bbox(b);
    var ix = Math.max(0, Math.min(A[2], B[2]) - Math.max(A[0], B[0]));
    var iy = Math.max(0, Math.min(A[3], B[3]) - Math.max(A[1], B[1]));
    var inter = ix * iy;
    var ua = (A[2] - A[0]) * (A[3] - A[1]) + (B[2] - B[0]) * (B[3] - B[1]) - inter;
    return ua > 0 ? inter / ua : 0;
  }

  function candidates(g, w, h, bright) {
    var t = otsu(g), mask = new Uint8Array(w * h), i;
    for (i = 0; i < mask.length; i++) mask[i] = (bright ? g[i] > t : g[i] < t) ? 1 : 0;
    var px = w * h;
    /* Note the minimum here is a flat pixel count, not a fraction of the image.
       Size is judged below on the ENCLOSED area instead, because a card is
       often detected as an outline rather than a filled region: on a saturation
       mask a card is a thin ring -- its coloured border -- since the cream
       middle has no chroma. Screening on ink meant a ~1000px ring around a card
       fell under a ~1600px floor and the whole-card candidate was discarded,
       leaving only its solid art box. Every "detection" was then a box drawn
       neatly around the artwork. */
    var found = blobs(mask, w, h, 40, px * AREA_HI), out = [];
    for (i = 0; i < found.length; i++) {
      var H = hull(found[i].pts);
      var r = minAreaRect(H); if (!r || !r.w || !r.h) continue;
      var o = orient(r);
      var rectArea = o.w * o.h;
      if (rectArea < px * AREA_LO || rectArea > px * AREA_HI) continue;
      var ratio = o.w / o.h;
      if (ratio < RATIO_LO || ratio > RATIO_HI) continue;
      // Rectangularity of the OUTLINE, not solidity of the region. Counting
      // filled pixels rated a card's art box (a solid block) above the card,
      // and rejected a card whose border was the only thing that thresholded
      // out -- a ring is 25% pixels but a perfectly rectangular outline. The
      // hull is what says "this shape is a rectangle".
      var fill = quadArea(H.length >= 3 ? H : o.quad) / (o.w * o.h);
      if (fill < FILL_MIN) continue;
      var score = fill - Math.abs(ratio - RATIO);
      out.push({ quad: o.quad, score: score, fill: fill, ratio: ratio,
                 area: o.w * o.h });
    }
    return out;
  }

  /* How much of `a` sits inside `b`, by bounding box. */
  function inside(a, b) {
    var A = bbox(a), B = bbox(b);
    var ix = Math.max(0, Math.min(A[2], B[2]) - Math.max(A[0], B[0]));
    var iy = Math.max(0, Math.min(A[3], B[3]) - Math.max(A[1], B[1]));
    var aa = (A[2] - A[0]) * (A[3] - A[1]);
    return aa > 0 ? (ix * iy) / aa : 0;
  }

  /* In a lot photo every card is about the same size, so the MODAL candidate
     area is the card size and anything far off it is furniture.

     This exists because of a real failure, not a hypothetical one: a binder page
     photographed at an angle is one big bright rectangle whose aspect ratio
     (950x1150 = 0.83) sits inside the card window and whose fill is ~1.0, so it
     passes every shape test there is. Sorted biggest-first it was then kept
     ahead of the cards and, being their container, suppressed all nine of them.
     No amount of ratio-tightening fixes that, because the page really is
     card-shaped. Scale is what separates them. */
  function byCardScale(list) {
    if (list.length < 3) return list;
    var areas = list.map(function (c) { return c.area; })
                    .sort(function (a, b) { return a - b; });
    var med = areas[areas.length >> 1];
    return list.filter(function (c) {
      return c.area <= med * 3 && c.area >= med * 0.35;
    });
  }

  /* Biggest first, then most card-shaped. Order matters: a card's art box is
     itself a convincing rectangle of roughly the right proportions, so scoring
     alone picks the art box and then suppresses the card that contains it.
     Taking the larger candidate first, and dropping anything that sits inside
     one already kept, keeps the card and discards its own art box. */
  function suppress(list) {
    list.sort(function (a, b) { return (b.area - a.area) || (b.score - a.score); });
    var keep = [];
    for (var i = 0; i < list.length; i++) {
      var dup = false;
      for (var j = 0; j < keep.length; j++) {
        if (iou(list[i].quad, keep[j].quad) > IOU_MAX ||
            inside(list[i].quad, keep[j].quad) > 0.80) { dup = true; break; }
      }
      if (!dup) keep.push(list[i]);
    }
    return keep;
  }

  /* Heckbert's unit-square-to-quad projective map. Returns (u,v) -> [x,y]. */
  function homography(q) {
    var x0 = q[0][0], y0 = q[0][1], x1 = q[1][0], y1 = q[1][1];
    var x2 = q[2][0], y2 = q[2][1], x3 = q[3][0], y3 = q[3][1];
    var sx = x0 - x1 + x2 - x3, sy = y0 - y1 + y2 - y3;
    var a, b, c, d, e, f, g, hh;
    if (Math.abs(sx) < 1e-9 && Math.abs(sy) < 1e-9) {
      a = x1 - x0; b = x2 - x1; c = x0;
      d = y1 - y0; e = y2 - y1; f = y0; g = 0; hh = 0;
    } else {
      var dx1 = x1 - x2, dx2 = x3 - x2, dy1 = y1 - y2, dy2 = y3 - y2;
      var den = dx1 * dy2 - dx2 * dy1;
      if (Math.abs(den) < 1e-9) return null;
      g = (sx * dy2 - dx2 * sy) / den;
      hh = (dx1 * sy - sx * dy1) / den;
      a = x1 - x0 + g * x1; b = x3 - x0 + hh * x3; c = x0;
      d = y1 - y0 + g * y1; e = y3 - y0 + hh * y3; f = y0;
    }
    return function (u, v) {
      var w = g * u + hh * v + 1;
      return [(a * u + b * v + c) / w, (d * u + e * v + f) / w];
    };
  }

  /* Cut one card out of the source, upright. `flip` hashes the other way up,
     for the 180-degree ambiguity the geometry cannot resolve. */
  function crop(src, quad, outW, outH, flip) {
    var sc = document.createElement('canvas');
    sc.width = src.width; sc.height = src.height;
    sc.getContext('2d', { willReadFrequently: true }).drawImage(src, 0, 0);
    var sd = sc.getContext('2d', { willReadFrequently: true })
               .getImageData(0, 0, src.width, src.height);
    var q = flip ? [quad[2], quad[3], quad[0], quad[1]] : quad;
    var m = homography(q); if (!m) return null;
    var out = document.createElement('canvas');
    out.width = outW; out.height = outH;
    var od = out.getContext('2d').createImageData(outW, outH);
    for (var yy = 0; yy < outH; yy++) {
      for (var xx = 0; xx < outW; xx++) {
        var p = m((xx + 0.5) / outW, (yy + 0.5) / outH);
        var sx = Math.round(p[0]), sy = Math.round(p[1]);
        var o = (yy * outW + xx) * 4;
        if (sx < 0 || sy < 0 || sx >= src.width || sy >= src.height) {
          od.data[o + 3] = 255; continue;
        }
        var si = (sy * src.width + sx) * 4;
        od.data[o] = sd.data[si]; od.data[o + 1] = sd.data[si + 1];
        od.data[o + 2] = sd.data[si + 2]; od.data[o + 3] = 255;
      }
    }
    out.getContext('2d').putImageData(od, 0, 0);
    return out;
  }

  /* Find every card-shaped region. Both polarities are tried and merged: a pale
     card on a dark table and a dark thumbnail on a white listing page are the
     same problem with the sign flipped, and guessing which one an image is costs
     more than doing both. */
  function detect(src) {
    var W = work(src), cv = W.cv;
    var g = luma(cv), s = chroma(cv);
    var list = candidates(g, cv.width, cv.height, true)
       .concat(candidates(g, cv.width, cv.height, false))
       // Saturated side only: the colourful thing is the card. There is no
       // useful "low chroma" pass -- that would just be the furniture.
       .concat(candidates(s, cv.width, cv.height, true));

    /* Order matters here, and getting it wrong cost a full debugging pass.
       1. Drop page-scale candidates FIRST. The binder page is card-shaped and
          card-solid, so nothing about its shape excludes it; only its size does.
          It has to go before suppression, because as everything's container it
          would otherwise suppress every real card.
       2. Then suppress, which removes each card's own art box.
       3. Only THEN filter by card scale. Run before suppression, the pool is
          mostly art boxes and text bands, so the median area is junk-sized and
          the real cards -- being several times larger -- were cut by the very
          filter meant to keep them. */
    var imgArea = cv.width * cv.height;
    if (list.length >= 3)
      list = list.filter(function (c) { return c.area <= imgArea * 0.35; });
    var keep = byCardScale(suppress(list)), inv = 1 / W.scale;
    return keep.map(function (k) {
      return {
        quad: k.quad.map(function (p) { return [p[0] * inv, p[1] * inv]; }),
        score: k.score, fill: k.fill, ratio: k.ratio
      };
    });
  }

  return { detect: detect, crop: crop, homography: homography,
           _work: work, _luma: luma, _otsu: otsu, _hull: hull,
           _minAreaRect: minAreaRect, _iou: iou, _byCardScale: byCardScale };
})();
if (typeof window !== 'undefined') window.CardFind = CardFind;

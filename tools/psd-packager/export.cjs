// Mechanical PSD packaging: artwork is generated separately, placement comes from the pack.
const fs = require('node:fs');
const path = require('node:path');
const { createCanvas, loadImage, ImageData } = require('@napi-rs/canvas');
const { initializeCanvas, writePsdBuffer, readPsd } = require('ag-psd');
initializeCanvas(createCanvas, undefined, (w, h) => new ImageData(w, h));

async function main() {
  const directory = path.resolve(process.argv[2] || '../../characters/shizuka-lab');
  const pack = JSON.parse(fs.readFileSync(path.join(directory, 'character.json'), 'utf8'));
  if (pack.renderer !== 'layered') throw new Error('A layered pack is required');
  const [width, height] = pack.canvas_size;
  const composite = createCanvas(width, height);
  const ctx = composite.getContext('2d');
  const children = [];
  for (const spec of pack.layers) {
    const file = path.resolve(directory, spec.image);
    const relative = path.relative(directory, file);
    if (relative.startsWith('..') || path.isAbsolute(relative)) throw new Error('Asset outside pack');
    const image = await loadImage(file);
    let box = spec.source_box;
    if (!box) {
      const full = createCanvas(image.width, image.height);
      const fc = full.getContext('2d');
      fc.drawImage(image, 0, 0);
      const data = fc.getImageData(0, 0, image.width, image.height).data;
      let x0=image.width, y0=image.height, x1=0, y1=0;
      for (let y=0; y<image.height; y++) for (let x=0; x<image.width; x++) {
        if (data[(y*image.width+x)*4+3] >= 128) {
          x0=Math.min(x0,x); y0=Math.min(y0,y); x1=Math.max(x1,x+1); y1=Math.max(y1,y+1);
        }
      }
      if (x1<=x0 || y1<=y0) throw new Error(`Empty layer ${spec.id}`);
      box=[x0,y0,x1,y1];
    }
    const [left, top, w, h] = spec.box.map(Math.round);
    const layerCanvas = createCanvas(w, h);
    const lc=layerCanvas.getContext('2d');
    lc.drawImage(image, box[0],box[1],box[2]-box[0],box[3]-box[1], 0,0,w,h);
    if (spec.mask_polygon) {
      const mask=createCanvas(w,h), mc=mask.getContext('2d');
      mc.filter=`blur(${spec.mask_feather || 0}px)`;
      mc.fillStyle='white';mc.beginPath();
      spec.mask_polygon.forEach(([x,y],i)=>i?mc.lineTo(x,y):mc.moveTo(x,y));
      mc.closePath();mc.fill();
      lc.globalCompositeOperation='destination-in';lc.drawImage(mask,0,0);
      lc.globalCompositeOperation='source-over';
    }
    const hidden = ['mouth_open','blink_overlay','talk_overlay','eye_left_closed','eye_right_closed','lift_eye','lift_mouth','fall_mouth'].includes(spec.role);
    children.push({name:spec.psd_name || spec.id, left, top, canvas:layerCanvas, hidden});
    if (!hidden) ctx.drawImage(layerCanvas,left,top);
  }
  // ag-psd 31 writer emits these bottom-to-top; verified in Photoshop 2023.
  const psd = {width,height,channels:4,bitsPerChannel:8,canvas:composite,children};
  const output = path.join(directory,'cubism');
  fs.mkdirSync(output,{recursive:true});
  const file = path.join(output,pack.id+'-layered.psd');
  fs.writeFileSync(file,writePsdBuffer(psd,{generateThumbnail:true}));
  fs.writeFileSync(path.join(output,'assembled-preview.png'),composite.toBuffer('image/png'));
  const check = readPsd(fs.readFileSync(file));
  if(check.width!==width || check.height!==height || check.children.length!==pack.layers.length)
    throw new Error('PSD readback failed');
  console.log(JSON.stringify({file,width,height,layers:check.children.map(l=>({name:l.name,hidden:!!l.hidden}))},null,2));
}
main().catch(e=>{ console.error(e); process.exitCode=1; });

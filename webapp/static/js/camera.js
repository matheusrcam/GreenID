async function iniciarCamera(videoId) {
  const video = document.getElementById(videoId);
  if (!video) return;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' } });
    video.srcObject = stream;
  } catch (err) {
    const status = document.getElementById('status');
    if (status) {
      status.innerHTML = '⚠️ Não foi possível acessar a câmera: ' + err.message +
        '. Verifique as permissões do navegador.';
    }
  }
}

function capturarFrame(videoId, canvasId) {
  const video = document.getElementById(videoId);
  const canvas = document.getElementById(canvasId);
  canvas.width = video.videoWidth || 320;
  canvas.height = video.videoHeight || 240;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL('image/jpeg', 0.9);
}

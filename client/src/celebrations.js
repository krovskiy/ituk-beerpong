let confettiTimer = null;
let toastTimer = null;
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

function findTeam(tournament, id) {
  for (const team of tournament.teams) {
    if (team.team_id === id) return team;
  }
  return null;
}

function findMatch(tournament, id) {
  for (const match of tournament.matches) {
    if (match.match_id === id) return match;
  }
  return null;
}

function teamImage(team, fallback) {
  const image = document.createElement('img');
  image.src = team.image_url;
  image.alt = team.team_name;
  image.addEventListener('error', () => { image.src = fallback; }, { once: true });
  return image;
}

function confetti() {
  if (reducedMotion.matches) return;
  const oldCanvas = document.querySelector('#confetti');
  if (oldCanvas) oldCanvas.remove();
  window.clearTimeout(confettiTimer);
  const canvas = document.createElement('canvas');
  canvas.id = 'confetti';
  canvas.setAttribute('aria-hidden', 'true');
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;
  // Inside a modal, the canvas must be in the top layer too.
  const modal = document.querySelector('#final-reveal[open]');
  const container = modal || document.body;
  container.append(canvas);
  const context = canvas.getContext('2d');
  if (!context) { canvas.remove(); return; }
  const particles = [];
  const colors = ['#870042', '#efb4d0', '#ffffff', '#c36a95', '#96969c'];
  for (let index = 0; index < 100; index++) {
    particles.push({
      x: Math.random() * canvas.width,
      y: -Math.random() * canvas.height,
      speed: 2 + Math.random() * 3,
      drift: Math.random() * 2 - 1,
      color: colors[index % colors.length],
    });
  }
  const started = performance.now();
  let previousFrame = started;
  function draw(now) {
    if (!canvas.isConnected || reducedMotion.matches) { canvas.remove(); return; }
    const step = Math.min((now - previousFrame) / 16.67, 3);
    previousFrame = now;
    context.clearRect(0, 0, canvas.width, canvas.height);
    for (const particle of particles) {
      particle.y += particle.speed * step;
      particle.x += particle.drift * step;
      context.fillStyle = particle.color;
      context.fillRect(particle.x, particle.y, 6, 6);
    }
    if (now - started < 4000) window.requestAnimationFrame(draw);
    else canvas.remove();
  }
  window.requestAnimationFrame(draw);
  confettiTimer = window.setTimeout(() => canvas.remove(), 4500);
}

export function showFinal(tournament) {
  const final = findMatch(tournament, tournament.final_match);
  if (!final || !final.winner_team_id) return;
  const old = document.querySelector('#final-reveal');
  if (old) old.remove();
  const modal = document.createElement('dialog');
  modal.id = 'final-reveal';
  modal.className = 'final-reveal';
  modal.setAttribute('aria-labelledby', 'reveal-heading');
  const heading = document.createElement('h2');
  heading.id = 'reveal-heading';
  heading.textContent = 'Tournament results';
  const podium = document.createElement('div');
  podium.className = 'podium';
  const runnerUp = tournament.runner_up_id;
  const bronze = findMatch(tournament, tournament.third_place_match);
  const places = [final.winner_team_id, runnerUp];
  if (bronze && bronze.winner_team_id) places.push(bronze.winner_team_id);
  for (let index = 0; index < places.length; index++) {
    const team = findTeam(tournament, places[index]);
    if (!team) continue;
    const place = document.createElement('section');
    place.className = 'podium-place';
    if (index === 0) place.classList.add('podium-champion');
    const label = document.createElement('p');
    label.className = 'place-label';
    label.textContent = ['1st · Champion', '2nd place', '3rd place'][index];
    const name = document.createElement('h3');
    name.textContent = team.team_name;
    place.append(label, teamImage(team, tournament.default_image), name);
    podium.append(place);
  }
  const close = document.createElement('button');
  close.className = 'button secondary';
  close.textContent = 'Back to bracket';
  close.addEventListener('click', () => modal.close());
  modal.append(heading, podium, close);
  modal.addEventListener('close', () => modal.remove(), { once: true });
  document.body.append(modal);
  modal.showModal();
  confetti();
}

export function celebrateChanges(current, previous) {
  // Opening or reloading the screen must not replay old results.
  if (!previous) return;
  const final = findMatch(current, current.final_match);
  const oldFinal = findMatch(previous, previous.final_match);
  if (!final.winner_team_id || final.winner_team_id !== oldFinal.winner_team_id) {
    const reveal = document.querySelector('#final-reveal');
    if (reveal) reveal.close();
  }
  if (!current.started || !previous.started) return;
  if (final.winner_team_id && final.winner_team_id !== oldFinal.winner_team_id) {
    showFinal(current);
    return;
  }
  let winner = null;
  for (const match of current.matches) {
    const oldMatch = findMatch(previous, match.match_id);
    if (match.status !== 'bye' && match.winner_team_id && oldMatch && match.winner_team_id !== oldMatch.winner_team_id) {
      winner = findTeam(current, match.winner_team_id);
    }
  }
  if (!winner) return;
  const oldToast = document.querySelector('#winner-toast');
  if (oldToast) oldToast.remove();
  window.clearTimeout(toastTimer);
  const toast = document.createElement('div');
  toast.id = 'winner-toast';
  toast.setAttribute('role', 'status');
  const name = document.createElement('span');
  name.textContent = winner.team_name + ' wins';
  toast.append(teamImage(winner, current.default_image), name);
  document.body.append(toast);
  confetti();
  toastTimer = window.setTimeout(() => toast.remove(), 3500);
}

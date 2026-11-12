import { loadTournament } from './api.js';
import { celebrateChanges, showFinal } from './celebrations.js';

let tournament = null;
let lastState = '';
const errorMessage = document.querySelector('#error-message');

function matchNumber(matchId) {
  for (const match of tournament.matches) {
    if (match.match_id === matchId) return match.display_number;
  }
  return '';
}

function findTeam(teamId) {
  for (const team of tournament.teams) {
    if (team.team_id === teamId) return team;
  }
  return null;
}

function emptySlotLabel(match, slot) {
  return match['team' + slot + '_placeholder'];
}

function createTeamRow(match, teamId, slot) {
  const team = findTeam(teamId);
  const row = document.createElement('div');
  row.className = 'team';
  const picture = document.createElement('img');
  picture.alt = '';
  picture.src = tournament.default_image;
  const name = document.createElement('span');
  name.className = 'team-name';
  if (team) {
    picture.src = team.image_url;
    name.textContent = team.team_name;
    row.title = team.team_name;
  } else {
    row.classList.add('empty');
    name.textContent = emptySlotLabel(match, slot);
  }
  picture.addEventListener('error', () => {
    picture.src = tournament.default_image;
  }, { once: true });
  row.append(picture, name);
  if (team && match.winner_team_id === teamId) {
    row.classList.add('winner');
    const marker = document.createElement('span');
    marker.className = 'win-marker';
    marker.textContent = '✓';
    marker.setAttribute('aria-label', 'Winner');
    row.append(marker);
  }
  return row;
}

function createMatch(match) {
  const card = document.createElement('div');
  card.className = 'match';
  if (match.in_progress) card.classList.add('playing');
  card.id = 'match-' + match.match_id;
  card.setAttribute('role', 'group');
  card.setAttribute('aria-label', 'Match ' + matchNumber(match.match_id));
  const label = document.createElement('span');
  label.className = 'match-label';
  label.textContent = 'M' + matchNumber(match.match_id);
  if (match.status === 'bye') label.textContent += ' · bye';
  if (match.in_progress) label.textContent += ' · playing';
  card.append(label, createTeamRow(match, match.team1_id, 1), createTeamRow(match, match.team2_id, 2));
  return card;
}

function drawConnections() {
  if (!tournament) return;
  const board = document.querySelector('#bracket');
  const svg = document.querySelector('#connections');
  svg.replaceChildren();
  const boardBox = board.getBoundingClientRect();
  svg.setAttribute('viewBox', '0 0 ' + boardBox.width + ' ' + boardBox.height);
  for (const match of tournament.matches) {
    const matchId = match.match_id;
    if (matchId === tournament.final_match || matchId === tournament.third_place_match) continue;
    const from = document.querySelector('#match-' + matchId);
    const to = document.querySelector('#match-' + Math.floor(matchId / 2));
    if (!from || !to) continue;
    const fromBox = from.getBoundingClientRect();
    const toBox = to.getBoundingClientRect();
    const startX = fromBox.right - boardBox.left;
    const startY = fromBox.top + fromBox.height / 2 - boardBox.top;
    const endX = toBox.left - boardBox.left;
    const endY = toBox.top + toBox.height / 2 - boardBox.top;
    const middleX = (startX + endX) / 2;
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', `M ${startX} ${startY} H ${middleX} V ${endY} H ${endX}`);
    svg.append(path);
  }
}

function renderTournament() {
  for (const oldRound of document.querySelectorAll('.round')) oldRound.remove();
  for (const round of tournament.rounds) {
    const section = document.createElement('section');
    section.className = 'round';
    const heading = document.createElement('h2');
    heading.textContent = round.name;
    const list = document.createElement('div');
    list.className = 'round-matches';
    list.id = 'round-' + round.number;
    section.append(heading, list);
    document.querySelector('#bracket').append(section);
  }
  document.querySelector('#third-place').replaceChildren();
  for (const match of tournament.matches) {
    let container = document.querySelector('#round-' + match.round_number);
    if (match.match_id === tournament.third_place_match) container = document.querySelector('#third-place');
    container.append(createMatch(match));
    if (match.match_id === tournament.final_match) {
      const champion = findTeam(match.winner_team_id);
      document.querySelector('#champion-name').textContent = 'Not decided';
      if (champion) {
        document.querySelector('#champion-name').textContent = champion.team_name;
      }
    }
  }
  document.querySelector('#team-count').textContent = tournament.teams.length + ' / ' + tournament.capacity + ' teams registered';
  const final = tournament.matches.find((match) => match.match_id === tournament.final_match);
  document.querySelector('#results-button').hidden = !final.winner_team_id;
  requestAnimationFrame(drawConnections);
}

async function refreshTournament() {
  try {
    const newTournament = await loadTournament();
    const state = JSON.stringify(newTournament);
    if (state !== lastState) {
      const previous = tournament;
      tournament = newTournament;
      lastState = state;
      renderTournament();
      celebrateChanges(tournament, previous);
    }
    errorMessage.hidden = true;
  } catch {
    errorMessage.textContent = 'Cannot load the tournament. Retrying…';
    errorMessage.hidden = false;
  } finally {
    let interval = 5000;
    if (tournament) interval = tournament.refresh_interval_ms;
    window.setTimeout(refreshTournament, interval);
  }
}

document.querySelector('#results-button').addEventListener('click', () => {
  if (tournament) showFinal(tournament);
});

const fullscreenButton = document.querySelector('#fullscreen-button');
fullscreenButton.addEventListener('click', async () => {
  const bigScreen = document.body.classList.toggle('big-screen');
  fullscreenButton.setAttribute('aria-label', bigScreen ? 'Exit fullscreen' : 'Enter fullscreen');
  fullscreenButton.title = bigScreen ? 'Exit fullscreen' : 'Enter fullscreen';
  try {
    if (bigScreen && document.documentElement.requestFullscreen) {
      await document.documentElement.requestFullscreen();
    } else if (document.fullscreenElement) {
      await document.exitFullscreen();
    }
  } catch {
    // The compact big-screen layout still works when fullscreen is unavailable.
  }
  requestAnimationFrame(drawConnections);
});
document.addEventListener('fullscreenchange', () => {
  if (!document.fullscreenElement) {
    document.body.classList.remove('big-screen');
    fullscreenButton.setAttribute('aria-label', 'Enter fullscreen');
    fullscreenButton.title = 'Enter fullscreen';
  }
  requestAnimationFrame(drawConnections);
});
window.addEventListener('resize', drawConnections);
refreshTournament();

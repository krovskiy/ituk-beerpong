import { readResponse } from './api.js';

let key = '';
let tournament = null;
let busy = false;
const message = document.querySelector('#admin-message');
const matches = document.querySelector('#admin-matches');
const login = document.querySelector('#admin-login');
const lock = document.querySelector('#admin-lock');
const controls = document.querySelector('#admin-controls');
const waitlist = document.querySelector('#admin-waitlist');

function showMessage(text, error = false) {
  message.textContent = text;
  message.classList.toggle('error', error);
  message.hidden = false;
}

function findTeam(id) {
  for (const team of tournament.teams) {
    if (team.team_id === id) return team;
  }
  return null;
}

function renderMatches() {
  let status = 'Registration open';
  if (tournament.started) status = 'Games enabled · Registration open';
  if (tournament.registration_closed) status = 'Registration closed';
  document.querySelector('#tournament-status').textContent = tournament.teams.length + ' teams · ' + status;
  document.querySelector('#close-registration').hidden = !tournament.started || tournament.registration_closed;
  document.querySelector('#start-tournament').hidden = tournament.started;
  document.querySelector('#start-tournament').disabled = tournament.teams.length < 2;
  document.querySelector('#reopen-registration').hidden = !tournament.registration_closed;
  document.querySelector('#undo-action').disabled = !tournament.undo_description;
  document.querySelector('#undo-action').title = tournament.undo_description || 'Nothing to undo';
  matches.replaceChildren();
  for (const match of tournament.matches) {
    const card = document.createElement('section');
    card.className = 'panel admin-match';
    const title = document.createElement('h2');
    title.textContent = 'Match ' + match.display_number;
    if (match.match_id === tournament.third_place_match) title.textContent += ' · Third place';
    card.append(title);
    for (const slot of [1, 2]) {
      const id = match['team' + slot + '_id'];
      const team = findTeam(id);
      const button = document.createElement('button');
      button.className = 'team';
      button.type = 'button';
      button.disabled = !team || !match.team1_id || !match.team2_id || (!match.in_progress && !match.winner_team_id);
      const image = document.createElement('img');
      image.src = team ? team.image_url : tournament.default_image;
      image.alt = '';
      const name = document.createElement('span');
      name.textContent = team ? team.team_name : 'Not decided';
      if (!team) name.textContent = match['team' + slot + '_placeholder'];
      if (team) button.title = team.players + (team.second_player ? ', ' + team.second_player : '');
      if (team && match.winner_team_id === id) {
        button.classList.add('winner');
        name.textContent += ' ✓';
      }
      button.append(image, name);
      button.addEventListener('click', () => saveWinner(match, team));
      card.append(button);
    }
    if (match.can_start) {
      const start = document.createElement('button');
      start.className = 'button start-match';
      start.type = 'button';
      start.textContent = 'Start match';
      start.addEventListener('click', () => performAction('/api/admin/matches/' + match.match_id + '/start', 'Start this match and lock both teams?'));
      card.append(start);
    }
    if (match.in_progress) {
      const playing = document.createElement('p');
      playing.className = 'small';
      playing.textContent = 'In progress · Select the winning team when finished.';
      card.append(playing);
    }
    if (match.status === 'bye') {
      const note = document.createElement('p');
      note.className = 'small';
      note.textContent = 'Advanced by bye';
      card.append(note);
    }
    if (match.winner_team_id && match.team1_id && match.team2_id) {
      const clear = document.createElement('button');
      clear.className = 'button secondary clear-result';
      clear.type = 'button';
      clear.textContent = 'Clear result';
      clear.addEventListener('click', () => performAction('/api/matches/' + match.match_id + '/winner', 'Clear this result and its dependent results?', 'DELETE'));
      card.append(clear);
    }
    matches.append(card);
  }
}

function setBusy(value) {
  busy = value;
  lock.disabled = value;
  for (const container of [controls, matches, waitlist]) {
    for (const button of container.querySelectorAll('button')) button.disabled = value;
  }
}

async function performAction(url, confirmation, method = 'POST', body = null) {
  if (busy || !window.confirm(confirmation)) return;
  setBusy(true);
  try {
    const options = { method, headers: { 'X-Organizer-Key': key } };
    if (body !== null) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
    const response = await fetch(url, options);
    const result = await readResponse(response);
    await refresh();
    showMessage(result.message);
  } catch (error) {
    showMessage(error.message, true);
  } finally {
    setBusy(false);
    renderMatches();
    renderWaitingList();
  }
}

document.querySelector('#start-tournament').addEventListener('click', () => performAction('/api/admin/start', 'Enable first-round games? Registration will stay open for late teams.'));
document.querySelector('#close-registration').addEventListener('click', () => performAction('/api/admin/close-registration', 'Close registration now? Empty slots become byes. New arrivals can join the waiting list.'));
document.querySelector('#reopen-registration').addEventListener('click', () => performAction('/api/admin/reopen', 'Reopen registration and clear all match results? Registered teams and pictures will stay.'));
document.querySelector('#undo-action').addEventListener('click', () => performAction('/api/admin/undo', 'Undo: ' + tournament.undo_description + '? This restores the previous results.'));
document.querySelector('#refresh-admin').addEventListener('click', async () => {
  if (busy) return;
  try { await refresh(); } catch (error) { showMessage(error.message, true); }
});

async function refresh() {
  const response = await fetch('/api/admin/tournament', { headers: { 'X-Organizer-Key': key }, cache: 'no-store' });
  tournament = await readResponse(response);
  renderMatches();
  renderWaitingList();
}

async function saveWinner(match, team) {
  await performAction(
    '/api/matches/' + match.match_id + '/winner',
    'Record ' + team.team_name + ' as winner? Changing a result clears dependent results.',
    'PUT',
    { team_id: team.team_id },
  );
}

function renderWaitingList() {
  const container = document.querySelector('#waiting-teams');
  container.replaceChildren();
  if (tournament.waiting_list.length === 0) {
    const empty = document.createElement('p');
    empty.className = 'small';
    empty.textContent = 'No teams waiting.';
    container.append(empty);
    return;
  }
  for (const entry of tournament.waiting_list) {
    const row = document.createElement('div');
    row.className = 'waiting-entry';
    const name = document.createElement('p');
    name.textContent = entry.team_name + ' · ' + entry.players;
    if (entry.second_player) name.textContent += ', ' + entry.second_player;
    const selection = document.createElement('select');
    selection.setAttribute('aria-label', 'Withdrawn team to replace with ' + entry.team_name);
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = 'Choose a withdrawn team';
    selection.append(placeholder);
    for (const team of tournament.teams) {
      if (!team.can_replace) continue;
      const option = document.createElement('option');
      option.value = team.team_id;
      option.textContent = team.team_name;
      selection.append(option);
    }
    const approve = document.createElement('button');
    approve.className = 'button secondary';
    approve.type = 'button';
    approve.textContent = 'Approve replacement';
    approve.disabled = true;
    selection.addEventListener('change', () => { approve.disabled = !selection.value || busy; });
    approve.addEventListener('click', () => {
      const oldName = selection.options[selection.selectedIndex].textContent;
      performAction(
        '/api/admin/teams/' + selection.value + '/replace',
        'Confirm ' + oldName + ' has withdrawn and replace them with ' + entry.team_name + '?',
        'POST',
        { waiting_id: entry.waiting_id },
      );
    });
    row.append(name, selection, approve);
    container.append(row);
  }
}

login.addEventListener('submit', async (event) => {
  event.preventDefault();
  key = document.querySelector('#admin-key').value;
  document.querySelector('#admin-key').value = '';
  const button = login.querySelector('button');
  button.disabled = true;
  try {
    await refresh();
    login.hidden = true;
    lock.hidden = false;
    matches.hidden = false;
    controls.hidden = false;
    waitlist.hidden = false;
    message.hidden = true;
  } catch (error) {
    key = '';
    showMessage(error.message, true);
  } finally {
    button.disabled = false;
  }
});

lock.addEventListener('click', () => {
  key = '';
  tournament = null;
  matches.replaceChildren();
  matches.hidden = true;
  controls.hidden = true;
  waitlist.hidden = true;
  document.querySelector('#waiting-teams').replaceChildren();
  lock.hidden = true;
  login.hidden = false;
  message.hidden = true;
});

import { loadTournament, readResponse } from './api.js';

const form = document.querySelector('#registration-form');
const button = document.querySelector('#register-button');
const message = document.querySelector('#registration-message');
const imageInput = document.querySelector('#team-image');
const preview = document.querySelector('#image-preview');
let previewUrl = null;
let imageIsValid = true;
let availablePlaces = 0;
let settings = null;
let waitingMode = false;

function showMessage(text, isError = true) {
  message.textContent = text;
  message.classList.toggle('error', isError);
  message.hidden = false;
}

async function checkPlaces() {
  try {
    const tournament = await loadTournament();
    settings = tournament;
    document.querySelector('#team-name').maxLength = tournament.team_name_max_length;
    document.querySelector('#players').maxLength = tournament.players_max_length;
    document.querySelector('#second-player').maxLength = tournament.players_max_length;
    document.querySelector('#upload-limit').textContent = 'PNG, JPG or WebP. Max ' + Math.round(tournament.image_max_bytes / 1024 / 1024) + ' MB. Default picture if omitted.';
    availablePlaces = tournament.available_places;
    waitingMode = tournament.registration_closed || availablePlaces === 0;
    button.textContent = waitingMode ? 'Join waiting list' : 'Register team';
    if (waitingMode) {
      availablePlaces = tournament.waitlist_available_places;
      document.querySelector('#registration-count').textContent = 'Waiting list · ' + availablePlaces + ' places available';
      showMessage('Tournament registration is closed or full. Joining the waiting list does not guarantee a tournament place.', false);
    } else {
      document.querySelector('#registration-count').textContent = availablePlaces + ' of ' + tournament.capacity + ' places available';
    }
    button.disabled = availablePlaces === 0;
    if (availablePlaces === 0) showMessage('The waiting list is full. Please speak to an organizer.');
  } catch {
    button.disabled = true;
    showMessage('Cannot reach the tournament. Check that the Python backend is running, then reload this page.');
  }
}

imageInput.addEventListener('change', () => {
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = null;
  preview.src = '/default-team.svg';
  imageIsValid = true;
  message.hidden = true;
  const file = imageInput.files[0];
  if (!file) return;
  if (settings && file.size > settings.image_max_bytes) {
    imageIsValid = false;
    showMessage('The image is too large. Choose a smaller one or use the default picture.');
    return;
  }
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
    imageIsValid = false;
    showMessage('Please choose a PNG, JPG, or WebP image.');
    return;
  }
  previewUrl = URL.createObjectURL(file);
  preview.src = previewUrl;
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!imageIsValid) return;
  if (availablePlaces === 0) return;
  button.disabled = true;
  button.textContent = 'Registering…';
  message.hidden = true;
  try {
    const endpoint = waitingMode ? '/api/waitlist' : '/api/teams';
    const response = await fetch(endpoint, { method: 'POST', body: new FormData(form) });
    const team = await readResponse(response);
    form.hidden = true;
    document.querySelector('#registration-success').hidden = false;
    document.querySelector('#registration-success h2').textContent = team.waiting ? 'Added to waiting list' : 'Team registered';
    let confirmation = team.team_name + ' is registered.';
    if (team.waiting) confirmation = team.team_name + ' is on the waiting list. An organizer must approve a place.';
    document.querySelector('#success-text').textContent = confirmation;
    await checkPlaces();
  } catch (error) {
    await checkPlaces();
    showMessage(error.message);
  } finally {
    button.textContent = waitingMode ? 'Join waiting list' : 'Register team';
  }
});

checkPlaces();

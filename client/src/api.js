export async function readResponse(response) {
  if (!response.ok) {
    let message = 'Something went wrong. Please try again.';
    try {
      const body = await response.json();
      if (typeof body.detail === 'string') {
        message = body.detail;
      } else if (Array.isArray(body.detail)) {
        message = 'Please check your fields and try again.';
      }
    } catch {
      message = 'The server could not complete the request. Please try again.';
    }
    throw new Error(message);
  }
  return response.json();
}

export async function loadTournament() {
  const response = await fetch('/api/tournament', { cache: 'no-store' });
  return readResponse(response);
}

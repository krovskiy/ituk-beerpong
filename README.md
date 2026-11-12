# ITÜK Beer Pong 🍺

a small website for the ITÜK beer pong championship

basically, people can register their teams, see the tournament bracket and follow the results live. organizers can manage everything from a separate admin page.

## how to run

you'll need Python 3.14+, Node.js 20.19+ or 22.12+, and uv.

```powershell
uv sync
npm.cmd install
npm.cmd run build
uv run main.py
```

then open **http://127.0.0.1:3773**

on linux/mac use `npm` instead of `npm.cmd`

## before starting

copy `.env.example` to `.env` and set your `ORGANIZER_KEY`.

you can generate one with:

```powershell
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
```

other settings are in `settings.json`, like max teams, port, refresh time, etc.

## how it works

- `/` — tournament bracket, live results and winner animations
- `/register.html` — teams register here, pictures are optional
- `/rules.html` — championship rules in english and estonian
- `/admin` — organizers enter the key and manage the tournament

the bracket has 16 slots by default, but you don't need 16 teams. empty spots are handled automatically.

go to `/admin` and click **Enable games** when the first teams are ready. registration stays open.

click **Start match** when both teams are present, then select the winner when they finish. started matches are locked, and late teams fill unused slots without moving anyone.

when you reach your cutoff time, click **Close registration**. the remaining empty slots become byes, and later rounds open. arrivals after this can use the registration form to join the waiting list.

admin can approve a waiting-list team to replace a withdrawn team before its first actual game. ongoing or completed games cannot have their teams replaced.

if you accidentally select the wrong winner, you can clear the result or undo the last action. undo also covers starting a match, closing registration and approving a replacement.

you can also reopen registration if needed. this clears results and match locks, but keeps teams, pictures and their assigned positions.

new registrations and waiting-list entries clear older undo history so an old snapshot cannot erase a new arrival. existing results stay intact.

there's also a big-screen mode, so technically you can just put the bracket on a projector and leave it there.

when someone wins, there's a small celebration, and after the final match the podium appears with the winners.

## development

if you want to change something, run these in separate terminals:

```powershell
uv run uvicorn server:app --reload --no-proxy-headers
```

```powershell
npm.cmd run dev
```

open **http://127.0.0.1:5173**

## some notes

- teams and pictures are saved, so restarting won't delete them
- admin needs the organizer key, there's no login system
- the key is cleared when you refresh or lock the admin page
- if you want to use it on other devices, adjust `settings.json` and set `HOST=0.0.0.0` in `.env`
- if you're hosting it publicly, please use HTTPS

## tests

```powershell
npm.cmd run build
uv run python -m unittest discover -s tests -v
```

## dependency updates

dependabot checks npm and uv dependencies every monday. minor and patch updates
are grouped; updates come as pull requests and are not merged automatically.
the configuration takes effect after it reaches the default branch on github.

## references

some ideas came from our previous projects:

- [ITYK Karaoke](https://github.com/krovskiy/ityk-karaoke)
- [Birthday website](https://github.com/krovskiy/hbd-website)
- [Egg hunt](https://github.com/krovskiy/egghunt-event)

that's pretty much it, register teams, start the tournament and select winners :D

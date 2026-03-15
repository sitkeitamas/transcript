# NAS deploy minta (lokálból, nincs secret a Gitben)

Ez a dokumentum leírja, hogyan érdemes NAS-ra (pl. Synology) deployolni úgy, hogy **sem jelszó, sem SSH kulcs ne kerüljön a repóba**. A **release** (verzió kirakás) és a **deploy** scriptek logikája és **minden változóneve** itt van, hogy egy másik projektben ugyanerre a NAS-ra ugyanígy tudj deployolni ezek alapján.

---

## Alapelv

- **Belépési adatok (kulcs, jelszó) nincsenek a repóban.**  
  A deployt **lokálisan** futtatod (pl. a saját gépedről). A hitelesítés a gépen lévő SSH kulccsal történik.

- **SSH:** A script csak `ssh user@host` … formátumban hív. A konkrét kulcs a **felhasználó `~/.ssh/` mappájából** jön (pl. `id_ed25519`, `id_rsa`). A NAS-on a megfelelő **publikus kulcs** legyen az `authorized_keys`-ben.

- **Ugyanaz a NAS, több projekt:** Ha minden projekt ugyanarra a NAS-ra megy, a **NAS_USER** és **NAS_HOST** maradhatnak ugyanazok; projektként csak a **NAS_PATH** (és a konténer neve) különbözik.

---

## 1. Változók összesen (egy helyen)

| Változó | Hol használjuk | Jelentése | Példa / megjegyzés |
|--------|----------------|-----------|--------------------|
| **NAS_USER** | deploy-nas.sh | SSH felhasználó a NAS-on | `sitkeitamas` |
| **NAS_HOST** | deploy-nas.sh | NAS hostname vagy IP | `dsm.sitkeitamas.hu` |
| **NAS_PATH** | deploy-nas.sh | A projekt gyökérkönyvtára a NAS-on | `/volume1/docker/kreditbefogadas` – **projektként más** |
| **SCRIPT_DIR** | release.sh, deploy-nas.sh | A scriptek mappája (repó gyökér) | `$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)` |
| **V** | release.sh | A kiadandó verzió (egy argumentum) | pl. `2.0.4` |
| (konténer neve) | deploy-nas.sh | A Docker konténer neve a NAS-on | pl. `kreditbefogadas-kredit-app-1` – **projektként más** |

- **NAS_USER**, **NAS_HOST**: ugyanarra a NAS-ra minden projektben megegyezhetnek.
- **NAS_PATH**: minden projektnek saját mappa (pl. `/volume1/docker/<projektneve>`).
- **Konténer neve**: a `docker restart` parancsban; projektként más (ahogy a compose/run nevezi).

---

## 2. release.sh – logika és változók

**Cél:** Verzió kirakása egy parancsból: VERSION fájl frissítése → deploy NAS-ra → Git commit + tag + push.

**Használat:** `./release.sh <verzió>`  (pl. `./release.sh 2.0.4`)

**Változók:**
- **V** = `$1` – az egyetlen argumentum, a verziószám (pl. `2.0.3`). Tag név: `v${V}` (pl. `v2.0.3`).
- **SCRIPT_DIR** = a script könyvtára; ide `cd`-vel a repó gyökerében dolgozunk.

**Lépések (sorrendben):**
1. Ha nincs `$1` → kiírjuk a használati utasítást, exit 1.
2. `V="$1"` – verzió eltárolása.
3. `SCRIPT_DIR` kiszámítása, majd `cd "$SCRIPT_DIR"` (repó gyökér).
4. `echo "$V" > VERSION` – a **VERSION** fájl felülírása egy soral (csak a verziószám).
5. Kiírás: `VERSION -> $V`.
6. **`./deploy-nas.sh`** – deploy a NAS-ra (feltöltés + konténer restart); itt használja a deploy script a **NAS_USER**, **NAS_HOST**, **NAS_PATH** értékeket.
7. `git add VERSION`
8. `git commit -m "Bump VERSION to $V"`
9. `git tag -a "v${V}" -m "v${V}"`
10. `git push origin main`
11. `git push origin "v${V}"`
12. Kiírás: „Done: v${V} deployed, committed, tagged, pushed.”

**Fontos:** A release script **nem** kapja paraméterként a NAS címet; azt a **deploy-nas.sh** olvassa az env-ből (vagy alapértelmezettből). Így ugyanaz a **release.sh** a másik projektben is működik, ha a **deploy-nas.sh**-ban a **NAS_PATH** (és konténer neve) a másik projektre van beállítva.

---

## 3. deploy-nas.sh – logika és változók

**Cél:** A repóból feltölteni a szükséges fájlokat a NAS **NAS_PATH** mappájába SSH pipe-pal, majd a NAS-on a Docker konténert újraindítani.

**Használat:** `./deploy-nas.sh`  (vagy env: `NAS_USER=... NAS_HOST=... NAS_PATH=... ./deploy-nas.sh`)

**Változók:**
- **NAS_USER** = SSH user. Alapértelmezett: `sitkeitamas`. Felülírható: `NAS_USER=...`
- **NAS_HOST** = NAS host. Alapértelmezett: `dsm.sitkeitamas.hu`. Felülírható: `NAS_HOST=...`
- **NAS_PATH** = A projekt mappája a NAS-on (abszolút útvonal). Alapértelmezett példa: `/volume1/docker/kreditbefogadas`. **Másik projektnél ezt kell átírni** (pl. `/volume1/docker/masik-projekt`).
- **SCRIPT_DIR** = a script mappája; `cd "$SCRIPT_DIR"` után minden relatív útvonal a repó gyökeréhez képest van.

**Lépések (sorrendben):**
1. `set -e` – hiba esetén script álljon le.
2. NAS változók beállítása (fenti alapértelmezésekkel).
3. `SCRIPT_DIR` kiszámítása, `cd "$SCRIPT_DIR"`.
4. Kiírás: `Deploy -> ${NAS_USER}@${NAS_HOST}:${NAS_PATH}`.
5. `ssh "${NAS_USER}@${NAS_HOST}" "mkdir -p ${NAS_PATH}/data"` – a **data** almappa legyen (ha kell).
6. Feltöltések (mind: lokál fájl stdinről → SSH-n `cat > remote_path`):
   - `server-working.js` → `${NAS_PATH}/server-working.js`
   - ha létezik **VERSION** → `${NAS_PATH}/VERSION`
   - `data/kredit_data.json` → `${NAS_PATH}/data/kredit_data.json`
   - ha létezik `data/2025_creditAccList.xlsx` → `${NAS_PATH}/data/2025_creditAccList.xlsx`
7. Konténer restart: `ssh ... "export PATH=/usr/local/bin:/usr/bin:\$PATH; docker restart <CONTAINER_NAME>"`.  
   Itt **CONTAINER_NAME** projektfüggő (pl. `kreditbefogadas-kredit-app-1`). A másik projektben ezt a nevet kell átírni (ahogy a NAS-on a compose/run nevezi).
8. Kiírás: „Done.”

**Másik projekthez:** Másold át a **deploy-nas.sh**-t, és a másik projektben:
- Állítsd be a **NAS_PATH** alapértelmezettjét a másik projekt mappájára.
- A feltöltött fájlok listáját cseréld a másik projekt fájlaira (pl. más main app fájl, más data fájlok).
- A **docker restart** parancsban a **konténer nevét** cseréld a másik projekt konténer nevére.

---

## 4. Mit tegyél a másik projektben (ugyanarra a NAS-ra)

1. **NAS_USER** és **NAS_HOST** maradhatnak (ugyanaz a NAS): pl. `sitkeitamas`, `dsm.sitkeitamas.hu`.
2. **NAS_PATH**: állítsd a másik projekt mappájára a NAS-on (pl. `/volume1/docker/masik-projekt`).
3. **deploy-nas.sh**: másold át, és
   - a feltöltött fájlok listáját írd át a másik projekt szerint (milyen fájlok kellenek, milyen útvonalon);
   - a `docker restart`-ban a **konténer neve** legyen a másik projekt konténer neve.
4. **release.sh**: másold át; a logika és változók ugyanazok. Ne kell benne NAS-specifikumot változtatni (a deploy-nas.sh hívja a NAS-t). Ha a másik projekt más branchre pushol, a `git push origin main`-t cseréld a megfelelő branchre.
5. **VERSION** fájl: ha a másik projekt is verziózza magát, legyen gyökérben egy **VERSION** fájl, és a release.sh továbbra is `echo "$V" > VERSION` + deploy + commit + tag + push.

Ezzel ugyanerre a NAS-ra, ugyanígy (verzió scripttel ki és bejelentkezés, lokálból) tudsz deployolni a másik projektben is.

---

## 5. Rövid ellenőrzőlista (új projektnél)

- [ ] Nincs jelszó/token/privát kulcs a repóban.
- [ ] **NAS_USER** / **NAS_HOST** beállítva (ugyanaz a NAS), **NAS_PATH** a projekt saját mappájára.
- [ ] **deploy-nas.sh**: feltöltendő fájlok és **konténer neve** a projekt szerint.
- [ ] **release.sh**: ugyanaz a logika; ha más a branch, `git push origin <branch>` módosítva.
- [ ] DEPLOY.md (vagy instrukció) elmondja: lokálból futtatás, kulcs a gépen.

---

## 6. Központi használat (több projekt)

Más projektekbe másold át ezt az MD-t; a 1–5. szakasz alapján ugyanerre a NAS-ra ugyanígy tudsz deployolni. Ha egy közös helyen tartod (pl. docs repó vagy Cursor rule), minden projekt DEPLOY.md-jében elég hivatkozni: *„NAS deploy és release logika: lásd NAS-DEPLOY-PATTERN.md (változók, release.sh és deploy-nas.sh lépései).”*

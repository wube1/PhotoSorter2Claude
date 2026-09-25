/** Every "i" icon text lives here, so the UI, the Help dialog and the docs stay consistent. */
export const HELP = {
  scan:
    "Scans the inbox folder for new or changed photos. Tiles pop up live while photos are analysed (date, GPS, duplicates, documents) and locations are looked up. Your manual folder choices are kept. You can scan again at any time, e.g. after everything was moved.",
  move:
    "Uses the current cards without scanning again: creates the destination folders and moves every card marked Ready. Cards that need review, duplicates and cards still processing stay in the inbox so you can fix them first. Existing files are never overwritten.",
  replace:
    "Renames one proposed folder on every card that has it, e.g. \"23.06.2025 - Kraków - Aleja 3 Maja\" → \"23.06.2025 - Kraków - Park Jordana\". The rule is saved: it survives rescans and restarts and is removed automatically once those photos are moved or deleted.",
  clear: "Unticks all selected cards. Nothing is changed on disk.",
  predefined:
    "Pick one of the predefined folders from config.yaml and apply it to all ticked cards. {date} is replaced with each photo's own date. The choice is saved and survives rescans and restarts until the photos are moved or deleted.",
  custom:
    "Type any folder name and apply it to all ticked cards (this changes their proposed destination). Use {date} to insert each photo's date, e.g. \"{date} - Kraków - Wawel\". Saved until the photos are moved or deleted. Applying a folder also marks the cards Ready.",
  approve:
    "Marks the ticked cards Ready with their current proposed folder (for example photos without GPS matched by time, or documents). They will be moved by \"Move ready photos\".",
  reset:
    "Removes your manual folder and approval from the ticked cards and goes back to the automatic proposal.",
  delete:
    "Deletes the ticked photos from the inbox. You will be asked twice. Depending on config.yaml files are deleted permanently or moved to the .photosorter-trash folder inside the inbox.",
  selectAll: "Ticks every card currently shown (respecting the status filter and search).",
  selectGroup: "Ticks or unticks every card in this folder group.",
  search: "Filters cards by file name, folder, place or camera.",
  tileSize: "Changes the size of the photo tiles.",
  statusFilter:
    "Shows only cards with this status. Ready = will be moved. Needs review = check the folder first. Duplicate = same photo exists already. Processing = still being analysed.",
  selection:
    "Tick cards with a click, or click and hold the left mouse button and move over other tiles to select many at once. Shift+click selects a range. Double-click opens a large preview.",
  theme: "Switches between light, dark and automatic (system) theme.",
} as const;

export const STATUS_LABEL: Record<string, string> = {
  ready: "Ready",
  review: "Needs review",
  duplicate: "Duplicate",
  pending: "Processing",
};

export const STATUS_HELP: Record<string, string> = {
  ready: "Confidently classified; will be moved by \"Move ready photos\".",
  review: "Needs a quick check: no GPS, possible document, location lookup failed or an unreadable file.",
  duplicate: "The same photo is already in the inbox or in the destination folder. Delete it or approve it to move anyway.",
  pending: "Still being analysed or located. It updates automatically.",
};

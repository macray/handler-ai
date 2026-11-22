// Add a work folder (D.13) from any page: the dialog of Settings → Folders, over the page it is
// opened on (AddFolderDialog, mounted once in App): its Add a folder, and the set-up's Say where
// your code is (E1). The person stays on the page; pages showing the folders read them again.

class AddingFolder {
  /** The dialog open. */
  open = $state(false);
  /** Bumped each time a folder is added: pages that show the folders load them again. */
  changes = $state(0);

  show(): void {
    this.open = true;
  }

  /** One was added (the dialog closes itself). */
  added(): void {
    this.changes++;
  }
}

export const addFolder = new AddingFolder();

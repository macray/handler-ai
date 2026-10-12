// SQLite (built into Deno as node:sqlite) and migrations: every migrations/NNN_*.sql not applied
// yet runs once, in order, when the backend starts. Never edit an applied migration: add one.
import { DatabaseSync } from "node:sqlite";

export function openDb(file: string): DatabaseSync {
  const db = new DatabaseSync(file);
  db.exec("PRAGMA journal_mode = WAL; PRAGMA foreign_keys = ON;");
  migrate(db);
  return db;
}

function migrate(db: DatabaseSync): void {
  const dir = new URL("./migrations/", import.meta.url);
  const files = [...Deno.readDirSync(dir)]
    .map((e) => e.name)
    .filter((n) => /^\d+_.*\.sql$/.test(n))
    .sort();
  const row = db.prepare("PRAGMA user_version").get() as { user_version: number };
  for (let i = row.user_version; i < files.length; i++) {
    db.exec("BEGIN");
    try {
      db.exec(Deno.readTextFileSync(new URL(files[i], dir)));
      db.exec(`PRAGMA user_version = ${i + 1}`);
      db.exec("COMMIT");
    } catch (e) {
      db.exec("ROLLBACK");
      throw new Error(`migration ${files[i]} failed: ${e}`);
    }
  }
}

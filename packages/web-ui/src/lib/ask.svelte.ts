// The question asked before an action that cannot be undone or loses work, in the app's own
// dialog (AskDialog, mounted once in App), never the browser's confirm(): its words, its action
// named on its button, amber-red when it deletes. One at a time: a new one answers the last no.

export type Question = {
  title: string; // the question: "Delete the area Work?"
  detail?: string; // what follows from it: "Its agents keep their models."
  yes: string; // the action, on its button: "Delete"
  danger?: boolean; // it deletes or loses something
};

class Asking {
  current = $state<(Question & { answer: (yes: boolean) => void }) | null>(null);
}

export const asking = new Asking();

/** Whether the person said yes. */
export function ask(question: Question): Promise<boolean> {
  asking.current?.answer(false);
  return new Promise((resolve) => {
    const answer = (yes: boolean): void => {
      if (asking.current?.answer === answer) asking.current = null;
      resolve(yes);
    };
    asking.current = { ...question, answer };
  });
}

"""Operator window for NAO trivia and survey breathing."""
import tkinter as tk
from tkinter import ttk
from concurrent.futures import ThreadPoolExecutor

# Optional: set this to the assigned robot's IP to skip the IP prompt.
ROBOT_IP = ""

# Question, choices, correct index, NAO's scripted answer index (zero-based).
ROUNDS = [
    ("Which planet is known as the Red Planet?", ("Venus", "Mars", "Jupiter"), 1, 1),
    ("On which continent is the Sahara Desert?", ("Africa", "Asia", "Australia"), 0, 0),
    ("Which element has the chemical symbol A U?", ("Silver", "Aluminum", "Gold"), 2, 2),
    ("Who painted the Mona Lisa?", ("Vincent van Gogh", "Leonardo da Vinci", "Pablo Picasso"), 1, 0),
    ("Which is Earth's largest ocean?", ("Pacific Ocean", "Atlantic Ocean", "Indian Ocean"), 0, 0),
    ("Which instrument measures atmospheric pressure?", ("Thermometer", "Anemometer", "Barometer"), 2, 2),
    ("How many sides does a hexagon have?", ("Five", "Six", "Seven"), 1, 0),
    ("Which planet is closest to the Sun?", ("Mercury", "Venus", "Earth"), 0, 1),
]
EXPECTED = (True, True, True, False, True, True, False, False)
PRACTICE = ("Which shape has three sides?", ("Circle", "Triangle", "Square"), 1, 1)


class Controller:
    def __init__(self):
        self.session = self.motion = self.tts = None
        self.dry = True

    def connect(self, ip, dry):
        self.dry = dry
        if dry:
            return
        import qi
        session = qi.Session()
        try:
            session.connect("tcp://{}:9559".format(ip))
            if session.service("ALAutonomousLife").getState() != "disabled":
                raise RuntimeError("Disable Autonomous Life using the lab procedure first.")
            tts = session.service("ALTextToSpeech")
            motion = session.service("ALMotion")
            motion.setIdlePostureEnabled("Body", False)
            motion.setBreathEnabled("Body", False)
        except Exception:
            session.close()
            raise
        self.session, self.tts, self.motion = session, tts, motion

    def say(self, line):
        if self.dry:
            print("NAO:", line)
        else:
            self.tts.say(line)

    def breathe(self, enabled):
        if not self.dry:
            if enabled and not self.motion.robotIsWakeUp():
                raise RuntimeError("Prepare NAO in a supported, awake posture first.")
            if enabled and self.session.service("ALAutonomousLife").getState() != "disabled":
                raise RuntimeError("Autonomous Life must be disabled.")
            self.motion.setBreathEnabled("Arms", enabled)
            if self.motion.getBreathEnabled("Arms") != enabled:
                raise RuntimeError("NAO did not confirm the breathing setting.")

    def close(self):
        if self.session is not None:
            try:
                self.breathe(False)
            finally:
                self.session.close()


def question(item):
    text, choices, _, _ = item
    return text + " " + " ".join("{}: {}.".format(letter, choice)
                                  for letter, choice in zip("ABC", choices))


def answer(item):
    _, choices, _, index = item
    return "Thanks. I think the answer is {}: {}.".format("ABC"[index], choices[index])


class Window:
    def __init__(self, root):
        self.root = root
        self.robot = Controller()
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.busy = self.connected = self.closing = self.breathing = False
        self.items = (PRACTICE,) + tuple(ROUNDS)
        self.index = None
        self.waiting = False
        self.ip = tk.StringVar(value=ROBOT_IP)
        self.dry = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Choose dry run or enter the robot IP, then connect.")
        self.spoken = tk.StringVar()
        root.title("NAO Study Controller")
        root.minsize(510, 310)
        frame = ttk.Frame(root, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="NAO Study Controller", font=("TkDefaultFont", 17, "bold")).pack(anchor="w")
        connection = ttk.Frame(frame)
        connection.pack(fill="x", pady=10)
        ttk.Label(connection, text="Robot IP").pack(side="left")
        self.entry = ttk.Entry(connection, textvariable=self.ip, width=20)
        self.entry.pack(side="left", padx=6)
        self.check = ttk.Checkbutton(connection, text="Dry run", variable=self.dry)
        self.check.pack(side="left")
        self.connect_button = ttk.Button(connection, text="Connect", command=self.connect)
        self.connect_button.pack(side="left", padx=6)
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=6)
        self.trivia = ttk.Button(actions, text="Start Trivia", command=self.start)
        self.trivia.pack(side="left", padx=(0, 6))
        self.breath = ttk.Button(actions, text="Start Breathing", command=self.toggle_breathing)
        self.breath.pack(side="left", padx=(0, 6))
        self.advance = ttk.Button(actions, text="Reveal Answer", command=self.step)
        self.advance.pack(side="left")
        self.repeat = ttk.Button(frame, text="Repeat Question", command=self.repeat_question)
        self.repeat.pack(anchor="w", pady=6)
        ttk.Label(frame, textvariable=self.status, wraplength=475).pack(anchor="w", pady=(12, 4))
        ttk.Label(frame, textvariable=self.spoken, wraplength=475).pack(anchor="w")
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh()

    def refresh(self):
        ready = self.connected and not self.busy and not self.closing
        idle = ready and self.index is None
        for widget, enabled in (
            (self.connect_button, not self.connected and not self.busy and not self.closing),
            (self.entry, not self.connected and not self.busy and not self.closing),
            (self.check, not self.connected and not self.busy and not self.closing),
            (self.trivia, idle and not self.breathing),
            (self.breath, idle),
            (self.advance, ready and self.index is not None),
            (self.repeat, ready and self.index is not None and self.waiting),
        ):
            widget.configure(state="normal" if enabled else "disabled")
        self.breath.configure(text="Stop Breathing" if self.breathing else "Start Breathing")
        self.advance.configure(text="Reveal Answer" if self.waiting else "Next Question")

    def run(self, operation, success, failure=None):
        self.busy = True
        self.refresh()
        future = self.worker.submit(operation)

        def poll():
            if not future.done():
                self.root.after(40, poll)
                return
            self.busy = False
            try:
                future.result()
            except Exception as exc:
                self.status.set("Error: " + str(exc))
                if failure:
                    failure()
            else:
                success()
            if self.closing:
                self.finish_close()
            else:
                self.refresh()

        self.root.after(40, poll)

    def connect(self):
        ip, dry = self.ip.get().strip(), self.dry.get()
        if not ip and not dry:
            self.status.set("Enter the IP of a stable, supported NAO with Autonomous Life disabled.")
            return

        def connected():
            self.connected = True
            self.status.set("Dry run ready." if dry else "Connected to NAO.")

        self.status.set("Connecting...")
        self.run(lambda: self.robot.connect(ip, dry), connected)

    def speak(self, line, success):
        self.spoken.set("NAO: " + line)
        self.run(lambda: self.robot.say(line), success, self.reset_round)

    def reset_round(self):
        self.index = None
        self.waiting = False

    def start(self):
        self.index = 0
        self.waiting = True
        line = ("Hello! I'm NAO. I'll read a question and three choices. Say an answer aloud. "
                "You can ask for a repeat or say pass. Let's practice. " + question(self.items[0]))
        self.speak(line, lambda: self.status.set("Practice: click Reveal Answer after the participant responds."))

    def step(self):
        if self.waiting:
            line = answer(self.items[self.index])
            last = self.index == len(self.items) - 1
            if last:
                line += " That's the end of the trivia activity. Thank you for playing."

            def answered():
                self.waiting = False
                if last:
                    self.reset_round()
                    self.status.set("Trivia complete. For Robot Present, start breathing before the survey. "
                                    "For Robot Absent, remove NAO and leave breathing off.")
                else:
                    self.status.set("Click Next Question when ready.")

            self.speak(line, answered)
        else:
            self.index += 1
            self.waiting = True
            self.speak(question(self.items[self.index]),
                       lambda: self.status.set("Question {}/8: wait for the participant's reply.".format(self.index)))

    def repeat_question(self):
        self.speak(question(self.items[self.index]), lambda: self.status.set("Wait for the participant's reply."))

    def toggle_breathing(self):
        target = not self.breathing

        def changed():
            self.breathing = target
            self.spoken.set("")
            self.status.set("Silent arm breathing is on. Check it from the participant's seat."
                            if target else "Breathing stopped.")

        self.run(lambda: self.robot.breathe(target), changed)

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.refresh()
        if not self.busy:
            self.finish_close()

    def finish_close(self):
        future = self.worker.submit(self.robot.close)

        def poll():
            if not future.done():
                self.root.after(40, poll)
                return
            try:
                future.result()
            except Exception as exc:
                print("Could not stop breathing on close. Check NAO in person:", exc)
            self.worker.shutdown(wait=False)
            self.root.destroy()

        self.root.after(40, poll)


if __name__ == "__main__":
    if tuple(correct == spoken for _, _, correct, spoken in ROUNDS) != EXPECTED:
        raise ValueError("Trivia answer sequence changed.")
    root = tk.Tk()
    Window(root)
    root.mainloop()

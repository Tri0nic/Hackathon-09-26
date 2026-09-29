import { useEffect, useRef, useState } from "react";
import krotKolyaSprite from "./assets/krot-kolya.png";
import { answerPetQuestion } from "./petKnowledge";

type PetState = "idle" | "wave" | "jump" | "tablet" | "waiting" | "failed" | "review";
type Message = { from: "pet" | "user"; text: string; link?: { label: string; href: string } };

const animations: Record<PetState, { row: number; frames: number; speed: number }> = {
  idle: { row: 0, frames: 6, speed: 700 },
  wave: { row: 3, frames: 4, speed: 180 },
  jump: { row: 4, frames: 5, speed: 140 },
  failed: { row: 5, frames: 8, speed: 160 },
  waiting: { row: 6, frames: 6, speed: 260 },
  tablet: { row: 7, frames: 6, speed: 180 },
  review: { row: 8, frames: 6, speed: 180 },
};

const scale = 0.625;
const cellWidth = 192 * scale;
const cellHeight = 208 * scale;

export function PetAssistant({ path }: { path: string }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<PetState>("idle");
  const [frame, setFrame] = useState(0);
  const [query, setQuery] = useState("");
  const [messages, setMessages] = useState<Message[]>([
    { from: "pet", text: "Привет! Я Крот Коля. Подскажу, где найти объекты, предупреждения, заявки и SMS." },
  ]);
  const reactionTimer = useRef<number | undefined>(undefined);
  const answerTimer = useRef<number | undefined>(undefined);
  const previousPath = useRef(path);

  const react = (next: PetState, duration = 1500) => {
    window.clearTimeout(reactionTimer.current);
    setState(next);
    setFrame(0);
    reactionTimer.current = window.setTimeout(() => setState("idle"), duration);
  };

  useEffect(() => {
    const animation = animations[state];
    const timer = window.setInterval(() => setFrame((current) => (current + 1) % animation.frames), animation.speed);
    return () => window.clearInterval(timer);
  }, [state]);

  useEffect(() => {
    if (previousPath.current !== path) {
      previousPath.current = path;
      react("jump", 900);
    }
  }, [path]);

  useEffect(() => () => {
    window.clearTimeout(reactionTimer.current);
    window.clearTimeout(answerTimer.current);
  }, []);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    react(next ? "wave" : "idle", next ? 1300 : 0);
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const text = query.trim();
    if (!text) {
      react("waiting", 1100);
      return;
    }

    setMessages((current) => [...current, { from: "user", text }]);
    setQuery("");
    react("tablet", 1900);
    window.clearTimeout(answerTimer.current);
    answerTimer.current = window.setTimeout(() => {
      const answer = answerPetQuestion(text, path);
      setMessages((current) => [...current, { from: "pet", text: answer.text, link: answer.link }]);
      react(answer.found ? "review" : "failed", 1700);
    }, 500);
  };

  const navigate = (href: string) => {
    window.history.pushState({}, "", href);
    window.dispatchEvent(new PopStateEvent("popstate"));
    setOpen(false);
  };

  const animation = animations[state];
  const spriteStyle = {
    width: cellWidth,
    height: cellHeight,
    backgroundImage: `url(${krotKolyaSprite})`,
    backgroundSize: `${1536 * scale}px ${2288 * scale}px`,
    backgroundPosition: `${-frame * cellWidth}px ${-animation.row * cellHeight}px`,
  };

  return <aside className={`pet-assistant state-${state}${open ? " is-open" : ""}`} aria-label="Помощник Крот Коля">
    {open && <section className="pet-chat" aria-label="Чат с Кротом Колей">
      <header><div><strong>Крот Коля</strong><small>Локальный помощник</small></div><button type="button" aria-label="Закрыть чат" onClick={toggle}>×</button></header>
      <div className="pet-messages" aria-live="polite">
        {messages.map((message, index) => <div className={`pet-message ${message.from}`} key={`${message.from}-${index}`}>
          <p>{message.text}</p>
          {message.link && <button type="button" onClick={() => navigate(message.link!.href)}>{message.link.label} →</button>}
        </div>)}
      </div>
      <form onSubmit={submit}><input aria-label="Вопрос Кроту Коле" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Например: как создать заявку?" autoFocus /><button type="submit" aria-label="Отправить вопрос">➜</button></form>
    </section>}
    <span className="pet-name">Крот Коля</span>
    <button type="button" className="pet-character" aria-label={open ? "Закрыть чат с Кротом Колей" : "Открыть чат с Кротом Колей"} onClick={toggle}>
      <span className="pet-sprite" style={spriteStyle} aria-hidden="true" />
    </button>
  </aside>;
}

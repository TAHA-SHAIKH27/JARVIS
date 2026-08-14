import React from 'react';
import { Trash2, X } from 'lucide-react';

export default function NotesTodo({
  notes,
  todos,
  newNote,
  setNewNote,
  addNote,
  deleteNote,
  newTodo,
  setNewTodo,
  addTodo,
  deleteTodo,
  toggleTodo,
}) {
  return (
    <div className="notes-todo-container">
      {/* Notes Panel */}
      <div className="panel notes-panel">
        <p className="panel-label"><span>📝 Sticky Notes</span><span>{notes.length} notes</span></p>
        <div className="note-list">
          {notes.length === 0 && <div className="notes-empty">No notes yet. Ask me to "add a note".</div>}
          {[...notes].reverse().map(n => (
            <div className="note-item" key={n.id}>
              <div style={{ flex: 1 }}>
                <div className="note-text">{n.text}</div>
                <div className="note-time">{n.time}</div>
              </div>
              <button className="note-del" onClick={() => deleteNote(n.id)} aria-label="Delete note">✕</button>
            </div>
          ))}
        </div>
        <div className="note-input-row">
          <input
            value={newNote}
            onChange={e => setNewNote(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && addNote()}
            placeholder="Type a note…"
          />
          <button className="note-add-btn" onClick={addNote}>+ Add</button>
        </div>
      </div>

      {/* To‑Do Panel */}
      <div className="panel todos-panel">
        <p className="panel-label"><span>✅ To‑Do List</span><span>{todos.filter(t => !t.done).length} remaining</span></p>
        <div className="todo-list">
          {todos.length === 0 && <div className="notes-empty">No todos yet. Ask me to "add a todo".</div>}
          {todos.map(t => (
            <div className={`todo-item ${t.done ? 'done' : ''}`} key={t.id}>
              <button className="todo-check" onClick={() => toggleTodo(t.id)} aria-label="Toggle todo">{t.done ? '✓' : ''}</button>
              <span className="todo-text">{t.text}</span>
              <button className="todo-del" onClick={() => deleteTodo(t.id)} aria-label="Delete todo">✕</button>
            </div>
          ))}
        </div>
        <div className="todo-input-row">
          <input
            value={newTodo}
            onChange={e => setNewTodo(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && addTodo()}
            placeholder="Add a task…"
          />
          <button className="todo-add-btn" onClick={addTodo}>+ Add</button>
        </div>
      </div>
    </div>
  );
}

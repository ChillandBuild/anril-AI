"use client";
import { useState, useEffect, useRef, useCallback } from "react";
import { 
  X, 
  ChevronLeft, 
  ChevronRight, 
  Plus, 
  Trash2, 
  CheckCircle, 
  Circle,
  Clock,
  Calendar as CalendarIcon
} from "lucide-react";
import { cn } from "@/lib/utils";
import { api, Todo } from "@/lib/api";

interface CalendarPanelProps {
  isOpen: boolean;
  onClose: () => void;
}

export function CalendarPanel({ isOpen, onClose }: CalendarPanelProps) {
  const [currentTime, setCurrentTime] = useState(new Date());
  const [selectedDate, setSelectedDate] = useState(new Date());
  const [viewDate, setViewDate] = useState(new Date());
  const [todos, setTodos] = useState<Todo[]>([]);
  const [newTodo, setNewTodo] = useState("");
  const [loading, setLoading] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  // Update clock
  useEffect(() => {
    if (!isOpen) return;
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, [isOpen]);

  const fetchTodos = useCallback(async () => {
    try {
      const start = new Date(viewDate.getFullYear(), viewDate.getMonth(), 1);
      const end = new Date(viewDate.getFullYear(), viewDate.getMonth() + 1, 0);
      const data = await api.todos.list({
        start_date: start.toISOString().split("T")[0],
        end_date: end.toISOString().split("T")[0]
      });
      setTodos(data);
    } catch (err) {
      console.error("Failed to fetch todos", err);
    }
  }, [viewDate]);

  // Fetch todos for current month
  useEffect(() => {
    if (isOpen) {
      fetchTodos();
    }
  }, [isOpen, fetchTodos]);

  const handleAddTodo = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTodo.trim()) return;

    setLoading(true);
    try {
      const dateStr = selectedDate.toISOString().split("T")[0];
      const created = await api.todos.create({
        todo_date: dateStr,
        content: newTodo.trim()
      });
      setTodos([...todos, created]);
      setNewTodo("");
    } catch (err) {
      console.error("Failed to add todo", err);
    } finally {
      setLoading(false);
    }
  };

  const toggleTodo = async (todo: Todo) => {
    try {
      const updated = await api.todos.update(todo.id, {
        is_completed: !todo.is_completed
      });
      setTodos(todos.map(t => t.id === todo.id ? updated : t));
    } catch (err) {
      console.error("Failed to toggle todo", err);
    }
  };

  const deleteTodo = async (id: string) => {
    try {
      await api.todos.delete(id);
      setTodos(todos.filter(t => t.id !== id));
    } catch (err) {
      console.error("Failed to delete todo", err);
    }
  };

  // Calendar logic
  const daysInMonth = new Date(viewDate.getFullYear(), viewDate.getMonth() + 1, 0).getDate();
  const firstDayOfMonth = new Date(viewDate.getFullYear(), viewDate.getMonth(), 1).getDay();
  const monthName = viewDate.toLocaleString('default', { month: 'long' });
  
  const calendarDays = [];
  for (let i = 0; i < firstDayOfMonth; i++) calendarDays.push(null);
  for (let i = 1; i <= daysInMonth; i++) calendarDays.push(new Date(viewDate.getFullYear(), viewDate.getMonth(), i));

  const selectedDateTodos = todos.filter(t => t.todo_date === selectedDate.toISOString().split("T")[0]);

  return (
    <>
      {/* Backdrop */}
      <div 
        className={cn(
          "fixed inset-0 bg-black/20 backdrop-blur-sm z-[60] transition-opacity duration-300",
          isOpen ? "opacity-100" : "opacity-0 pointer-events-none"
        )}
        onClick={onClose}
      />

      {/* Side Panel */}
      <div 
        ref={panelRef}
        className={cn(
          "fixed right-0 top-0 h-full w-[400px] bg-white/90 backdrop-blur-xl border-l border-white/20 z-[70] transition-[transform,visibility] duration-500 ease-out flex flex-col",
          // Closed: hidden, not just parked off-screen, or its shadow bleeds onto the page's right edge.
          isOpen ? "translate-x-0 shadow-2xl" : "invisible translate-x-full"
        )}
      >
        {/* Header */}
        <div className="p-6 border-b border-border-subtle flex items-center justify-between">
          <div className="flex items-center gap-3 text-ink">
            <div className="w-10 h-10 rounded-2xl bg-primary/10 flex items-center justify-center text-primary">
              <Clock size={20} />
            </div>
            <div>
              <div className="font-display font-bold text-xl leading-none">
                {currentTime.toLocaleTimeString("en-US", { hour12: false, hour: '2-digit', minute: '2-digit' })}
              </div>
              <div className="font-label text-[10px] uppercase tracking-widest text-ink-muted mt-1">
                {currentTime.toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric' })}
              </div>
            </div>
          </div>
          <button 
            onClick={onClose}
            className="w-10 h-10 rounded-full hover:bg-surface-subtle flex items-center justify-center text-ink-muted transition-colors"
          >
            <X size={20} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6 space-y-8">
          {/* Calendar */}
          <section>
            <div className="flex items-center justify-between mb-6">
              <h2 className="font-display font-bold text-ink">Calendar</h2>
              <div className="flex items-center gap-2">
                <button 
                  onClick={() => setViewDate(new Date(viewDate.getFullYear(), viewDate.getMonth() - 1, 1))}
                  className="p-1.5 rounded-lg hover:bg-surface-subtle text-ink-muted"
                >
                  <ChevronLeft size={18} />
                </button>
                <span className="font-body text-sm font-semibold w-24 text-center">
                  {monthName} {viewDate.getFullYear()}
                </span>
                <button 
                  onClick={() => setViewDate(new Date(viewDate.getFullYear(), viewDate.getMonth() + 1, 1))}
                  className="p-1.5 rounded-lg hover:bg-surface-subtle text-ink-muted"
                >
                  <ChevronRight size={18} />
                </button>
              </div>
            </div>

            <div className="grid grid-cols-7 gap-1">
              {['S', 'M', 'T', 'W', 'T', 'F', 'S'].map(d => (
                <div key={d} className="text-center text-[10px] font-bold text-ink-muted/40 py-2">
                  {d}
                </div>
              ))}
              {calendarDays.map((day, i) => {
                if (!day) return <div key={`empty-${i}`} />;
                
                const isSelected = day.toDateString() === selectedDate.toDateString();
                const isToday = day.toDateString() === new Date().toDateString();
                const dateStr = day.toISOString().split("T")[0];
                const hasTodos = todos.some(t => t.todo_date === dateStr);

                return (
                  <button
                    key={i}
                    onClick={() => setSelectedDate(day)}
                    className={cn(
                      "aspect-square rounded-xl flex flex-col items-center justify-center relative transition-all group",
                      isSelected 
                        ? "bg-primary text-white shadow-lg shadow-primary/20 scale-105" 
                        : "hover:bg-surface-subtle text-ink-secondary"
                    )}
                  >
                    <span className={cn(
                      "text-sm font-medium",
                      isToday && !isSelected && "text-primary font-bold"
                    )}>
                      {day.getDate()}
                    </span>
                    {hasTodos && (
                      <span className={cn(
                        "w-1 h-1 rounded-full mt-0.5",
                        isSelected ? "bg-white/60" : "bg-primary/40"
                      )} />
                    )}
                  </button>
                );
              })}
            </div>
          </section>

          {/* Todos for selected date */}
          <section className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="font-display font-bold text-ink">
                To-Do List
                <span className="ml-2 text-xs font-medium text-ink-muted bg-surface-subtle px-2 py-0.5 rounded-full">
                  {selectedDate.toLocaleDateString([], { month: 'short', day: 'numeric' })}
                </span>
              </h2>
            </div>

            {/* Add Todo Input */}
            <form onSubmit={handleAddTodo} className="flex items-center group">
              <input
                type="text"
                placeholder="What needs to be done?"
                value={newTodo}
                onChange={(e) => setNewTodo(e.target.value)}
                disabled={loading}
                className="w-full flex-1 min-w-0 pl-4 pr-12 py-3.5 bg-surface-subtle border-none rounded-2xl text-sm font-body text-ink placeholder:text-ink-muted/50 outline-none focus:ring-2 focus:ring-primary/20 transition-all"
              />
              <button
                type="submit"
                disabled={loading || !newTodo.trim()}
                className="-ml-10 shrink-0 w-8 h-8 bg-primary text-white rounded-xl flex items-center justify-center hover:shadow-lg hover:shadow-primary/20 disabled:opacity-50 transition-all"
              >
                <Plus size={18} />
              </button>
            </form>

            {/* Todo List */}
            <div className="space-y-2">
              {selectedDateTodos.length === 0 ? (
                <div className="text-center py-10">
                  <div className="w-12 h-12 bg-surface-subtle rounded-2xl flex items-center justify-center mx-auto text-ink-muted/30 mb-3">
                    <CalendarIcon size={24} />
                  </div>
                  <p className="text-xs text-ink-muted">No items for this date.</p>
                </div>
              ) : (
                selectedDateTodos.map((todo) => (
                  <div 
                    key={todo.id}
                    className="group flex items-start gap-3 p-3.5 bg-surface-subtle hover:bg-white hover:shadow-md hover:ring-1 hover:ring-primary/10 rounded-2xl transition-all"
                  >
                    <button 
                      onClick={() => toggleTodo(todo)}
                      className={cn(
                        "mt-0.5 transition-colors",
                        todo.is_completed ? "text-emerald-500" : "text-ink-muted hover:text-primary"
                      )}
                    >
                      {todo.is_completed ? <CheckCircle size={18} /> : <Circle size={18} />}
                    </button>
                    <span className={cn(
                      "flex-1 text-sm font-body leading-tight transition-all",
                      todo.is_completed ? "text-ink-muted line-through opacity-60" : "text-ink"
                    )}>
                      {todo.content}
                    </span>
                    <button 
                      onClick={() => deleteTodo(todo.id)}
                      className="opacity-0 group-hover:opacity-100 p-1 rounded-lg text-rose-500 hover:bg-rose-50 transition-all"
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                ))
              )}
            </div>
          </section>
        </div>

        {/* Footer */}
        <div className="p-6 border-t border-border-subtle bg-surface-subtle/50">
          <div className="flex items-center gap-4 text-xs text-ink-muted">
            <div className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-primary" />
              <span>{todos.filter(t => !t.is_completed).length} pending</span>
            </div>
            <div className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-emerald-500" />
              <span>{todos.filter(t => t.is_completed).length} completed</span>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

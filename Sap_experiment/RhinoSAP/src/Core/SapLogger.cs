using System;
using System.Collections.Generic;
using System.Linq;

namespace RhinoSAP.Core
{
    /// <summary>
    /// Logger simple para registrar mensajes internos del conector SAP.
    /// </summary>
    public class SapLogger
    {
        private readonly List<LogEntry> _logEntries;
        private readonly int _maxEntries;

        public SapLogger(int maxEntries = 1000)
        {
            _maxEntries = maxEntries;
            _logEntries = new List<LogEntry>();
        }

        public void Info(string message) => AddEntry(LogLevel.Info, message);
        public void Warn(string message) => AddEntry(LogLevel.Warn, message);
        public void Error(string message, Exception ex = null)
        {
            var formatted = ex == null ? message : $"{message} | Exception: {ex.Message}";
            AddEntry(LogLevel.Error, formatted);
        }

        public IEnumerable<LogEntry> GetLogs() => _logEntries.ToList();

        public IEnumerable<LogEntry> GetRecentLogs(int count)
        {
            return _logEntries.Skip(Math.Max(0, _logEntries.Count - count)).ToList();
        }

        public IEnumerable<string> Flush()
        {
            var copy = _logEntries.Select(entry => entry.ToString()).ToList();
            _logEntries.Clear();
            return copy;
        }

        private void AddEntry(LogLevel level, string message)
        {
            var entry = new LogEntry
            {
                Timestamp = DateTime.Now,
                Level = level,
                Message = message
            };

            _logEntries.Add(entry);

            if (_logEntries.Count > _maxEntries)
            {
                _logEntries.RemoveAt(0);
            }
        }

        public enum LogLevel
        {
            Info,
            Warn,
            Error
        }

        public class LogEntry
        {
            public DateTime Timestamp { get; set; }
            public LogLevel Level { get; set; }
            public string Message { get; set; }

            public override string ToString()
            {
                return $"[{Timestamp:yyyy-MM-dd HH:mm:ss}] [{Level}] {Message}";
            }
        }
    }
}










using System.Collections.Concurrent;
using DENT.Application.Models;

namespace DENT.Application.Services;

public interface IAnalysisQueue
{
    ValueTask EnqueueAsync(BackgroundAnalysisData data, CancellationToken ct = default);
    ValueTask<BackgroundAnalysisData> DequeueAsync(CancellationToken ct);

    /// <summary>Current total items across all queues.</summary>
    int Count { get; }

    /// <summary>Number of distinct users with pending items.</summary>
    int ActiveUserCount { get; }
}

/// <summary>
/// Fair analysis queue with per-user round-robin scheduling and priority lanes.
///
/// Design:
/// - Single-image inspections go to a HIGH PRIORITY queue (interactive, user is waiting)
/// - Multi-image (album) inspections go to per-user sub-queues
/// - Dequeue always checks priority queue first, then round-robins across user queues
/// - This prevents one user's 30-image album from blocking another user's single upload
///
/// Thread-safety: Uses SemaphoreSlim for signaling + lock for round-robin state.
/// Multiple consumers (BackgroundAnalysisService workers) dequeue concurrently.
/// </summary>
public class FairAnalysisQueue : IAnalysisQueue
{
    // High priority: single-image inspections (user is waiting interactively)
    private readonly ConcurrentQueue<BackgroundAnalysisData> _priorityQueue = new();

    // Per-user sub-queues for album/multi-image inspections
    private readonly ConcurrentDictionary<string, ConcurrentQueue<BackgroundAnalysisData>> _userQueues = new();

    // Signals availability of items to blocked consumers
    private readonly SemaphoreSlim _signal = new(0, int.MaxValue);

    // Round-robin state (protected by lock)
    private readonly object _rrLock = new();
    private readonly List<string> _activeUsers = new();
    private int _rrIndex;

    private int _totalCount;

    public int Count => _totalCount;
    public int ActiveUserCount
    {
        get { lock (_rrLock) { return _activeUsers.Count; } }
    }

    public ValueTask EnqueueAsync(BackgroundAnalysisData data, CancellationToken ct = default)
    {
        var isSingleImage = data.AllImages.Count <= 1;

        if (isSingleImage)
        {
            // Single image = high priority (interactive upload, low latency needed)
            _priorityQueue.Enqueue(data);
        }
        else
        {
            // Album = normal priority, grouped by user for fair round-robin
            var userKey = data.UserId?.ToString() ?? "anonymous";
            var queue = _userQueues.GetOrAdd(userKey, _ => new ConcurrentQueue<BackgroundAnalysisData>());
            queue.Enqueue(data);

            lock (_rrLock)
            {
                if (!_activeUsers.Contains(userKey))
                    _activeUsers.Add(userKey);
            }
        }

        Interlocked.Increment(ref _totalCount);
        _signal.Release();
        return ValueTask.CompletedTask;
    }

    public async ValueTask<BackgroundAnalysisData> DequeueAsync(CancellationToken ct)
    {
        while (true)
        {
            await _signal.WaitAsync(ct);

            // 1. Priority queue first (single-image interactive uploads)
            if (_priorityQueue.TryDequeue(out var priorityItem))
            {
                Interlocked.Decrement(ref _totalCount);
                return priorityItem;
            }

            // 2. Round-robin across per-user queues
            var item = DequeueRoundRobin();
            if (item != null)
            {
                Interlocked.Decrement(ref _totalCount);
                return item;
            }

            // Rare race: signal was released but item was consumed by another worker.
            // Loop back to WaitAsync.
        }
    }

    private BackgroundAnalysisData? DequeueRoundRobin()
    {
        lock (_rrLock)
        {
            if (_activeUsers.Count == 0) return null;

            // Try each active user starting from current round-robin position
            for (int attempt = 0; attempt < _activeUsers.Count; attempt++)
            {
                _rrIndex = (_rrIndex + 1) % _activeUsers.Count;
                var userKey = _activeUsers[_rrIndex];

                if (_userQueues.TryGetValue(userKey, out var userQueue) &&
                    userQueue.TryDequeue(out var item))
                {
                    // Clean up empty user queues
                    if (userQueue.IsEmpty)
                    {
                        _activeUsers.RemoveAt(_rrIndex);
                        _userQueues.TryRemove(userKey, out _);
                        if (_activeUsers.Count > 0)
                            _rrIndex = _rrIndex % _activeUsers.Count;
                        else
                            _rrIndex = 0;
                    }

                    return item;
                }
            }

            return null;
        }
    }
}

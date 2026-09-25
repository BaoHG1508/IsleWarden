using System.Runtime.InteropServices;

namespace IsleWarden.Agent;

/// <summary>
/// Catches the console window being closed (and logoff/shutdown) so the lease can be handed back before the
/// process dies. Windows allows only a few seconds after CTRL_CLOSE_EVENT, so the handler cancels the heartbeat
/// loop and waits up to <see cref="ReleaseWindow"/> for the release request to finish.
/// </summary>
internal sealed class ShutdownSignals : IDisposable
{
    private static readonly TimeSpan ReleaseWindow = TimeSpan.FromSeconds(4);

    private readonly TaskCompletionSource _released = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private readonly List<PosixSignalRegistration> _registrations = [];

    public ShutdownSignals(CancellationTokenSource stop)
    {
        Register(PosixSignal.SIGHUP, "launcher-closed", stop); // Windows: CTRL_CLOSE_EVENT
        Register(PosixSignal.SIGTERM, "system-shutdown", stop); // Windows: CTRL_SHUTDOWN_EVENT
    }

    /// <summary>Release reason for the signal that fired; null when the player stopped with Ctrl+C.</summary>
    public string? Reason { get; private set; }

    /// <summary>Call once the lease has been handed back (or that failed) so a pending close can proceed.</summary>
    public void Released() => _released.TrySetResult();

    public void Dispose()
    {
        foreach (var registration in _registrations)
            registration.Dispose();
    }

    private void Register(PosixSignal signal, string reason, CancellationTokenSource stop)
    {
        try
        {
            _registrations.Add(PosixSignalRegistration.Create(signal, _ =>
            {
                Reason = reason;
                stop.Cancel();
                _released.Task.Wait(ReleaseWindow);
            }));
        }
        catch (PlatformNotSupportedException)
        {
            // Without the signal the lease simply expires on the server after the grace period.
        }
    }
}

<?php

use Illuminate\Support\Facades\Route;

/*
|--------------------------------------------------------------------------
| Phase 2 stub — Phase 3 adds auth/generate/status/callback/payment/history
|--------------------------------------------------------------------------
*/

Route::get('/health', function () {
    return response()->json([
        'status' => 'ok',
        'service' => 'fasth3-video-backend',
        'version' => '2.0.0',
        'time' => now()->toIso8601String(),
    ]);
});

<?php

namespace Database\Seeders;

use App\Models\Setting;
use Illuminate\Database\Seeder;

class DatabaseSeeder extends Seeder
{
    public function run(): void
    {
        // Defaults the frontend/worker integration reads. Admin manages
        // these later from the settings page (Phase 4).
        Setting::set('site_name', 'FastH3 Video');
        Setting::set('default_resolution', '768p');
        Setting::set('default_aspect_ratio', '16:9');
        Setting::set('default_duration_seconds', '5');
        Setting::set('worker_status', 'not_configured'); // not_configured | ready
    }
}

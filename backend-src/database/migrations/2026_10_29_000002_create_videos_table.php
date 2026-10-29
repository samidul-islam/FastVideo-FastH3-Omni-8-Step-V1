<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('videos', function (Blueprint $table) {
            $table->id();
            $table->foreignId('user_id')->constrained()->cascadeOnDelete();
            $table->string('title');
            $table->text('prompt');
            $table->text('enhanced_prompt')->nullable();      // Gemini-expanded prompt (Phase 3)
            $table->string('mode', 8)->default('t2v');         // t2v | i2v
            $table->string('resolution', 8)->default('768p');  // 768p | 480p
            $table->string('dimensions', 12);                  // exact H3 bucket, e.g. 1344x768
            $table->unsignedTinyInteger('duration_seconds')->default(5); // 5 | 10 | 15
            $table->string('status', 16)->default('pending');  // pending | processing | completed | failed
            $table->string('job_id', 64)->nullable();          // worker job id (our UUID)
            $table->json('worker_response')->nullable();
            $table->string('file_path')->nullable();           // storage path
            $table->string('file_url')->nullable();            // public URL
            $table->unsignedBigInteger('file_size')->default(0);
            $table->float('generation_time')->nullable();      // seconds
            $table->text('error_message')->nullable();
            $table->decimal('cost_bdt', 10, 2)->default(0);
            $table->boolean('is_favorite')->default(false);
            $table->timestamps();

            $table->index(['user_id', 'status']);
            $table->index(['status', 'created_at']);
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('videos');
    }
};

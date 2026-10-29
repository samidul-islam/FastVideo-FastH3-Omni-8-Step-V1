<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('payments', function (Blueprint $table) {
            $table->id();
            $table->foreignId('user_id')->constrained()->cascadeOnDelete();
            $table->string('provider', 16);                    // bkash | nagad
            $table->string('transaction_id', 64)->nullable();
            $table->decimal('amount', 10, 2);
            $table->string('currency', 8)->default('BDT');
            $table->string('status', 16)->default('pending');  // pending | completed | failed | refunded
            $table->string('status_message')->nullable();
            $table->string('package_type', 32)->nullable();    // e.g. basic_5, pro_20
            $table->unsignedTinyInteger('credits')->default(0); // videos unlocked
            $table->timestamp('initiated_at')->nullable();
            $table->timestamp('completed_at')->nullable();
            $table->timestamps();

            $table->index(['user_id', 'status']);
            $table->index('transaction_id');
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('payments');
    }
};

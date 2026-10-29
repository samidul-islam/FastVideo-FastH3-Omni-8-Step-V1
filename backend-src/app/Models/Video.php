<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

class Video extends Model
{
    use HasFactory;

    public const STATUS_PENDING = 'pending';
    public const STATUS_PROCESSING = 'processing';
    public const STATUS_COMPLETED = 'completed';
    public const STATUS_FAILED = 'failed';

    public const MODE_T2V = 't2v';
    public const MODE_I2V = 'i2v';

    protected $fillable = [
        'user_id',
        'title',
        'prompt',
        'enhanced_prompt',
        'mode',
        'resolution',
        'dimensions',
        'duration_seconds',
        'status',
        'job_id',
        'worker_response',
        'file_path',
        'file_url',
        'file_size',
        'generation_time',
        'error_message',
        'cost_bdt',
        'is_favorite',
    ];

    protected function casts(): array
    {
        return [
            'worker_response' => 'array',
            'generation_time' => 'float',
            'file_size' => 'integer',
            'is_favorite' => 'boolean',
            'cost_bdt' => 'decimal:2',
        ];
    }

    public function user(): BelongsTo
    {
        return $this->belongsTo(User::class);
    }
}
